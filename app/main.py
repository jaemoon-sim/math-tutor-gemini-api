from __future__ import annotations

import ipaddress
import json
import mimetypes
import os
import socket
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from google import genai
from google.genai import types
from pydantic import BaseModel, Field, HttpUrl


load_dotenv()

APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent
DEFAULT_CURRICULUM_DIR = PROJECT_ROOT / "curriculum"

DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
MAX_IMAGE_BYTES = int(os.getenv("MAX_IMAGE_BYTES", str(10 * 1024 * 1024)))
ALLOW_PRIVATE_IMAGE_URLS = os.getenv("ALLOW_PRIVATE_IMAGE_URLS", "").lower() in {
    "1",
    "true",
    "yes",
}


SYSTEM_INSTRUCTION = """
너는 대한민국 중학교 수학 교육과정에 맞춰 설명하는 수학 튜터다.
사용자의 현재 진도와 교육과정 맥락을 우선한다.
아직 배우지 않은 개념, 고등학교식 풀이, 불필요하게 빠른 편법은 기본 풀이에 쓰지 않는다.
문제 이미지가 흐리거나 읽기 어려우면 추측하지 말고 확인이 필요한 부분을 말한다.
풀이가 끝나면 오답노트와 복습 추천에 저장하기 좋은 구조로 답한다.
""".strip()


class SolveRequest(BaseModel):
    image_url: HttpUrl = Field(..., description="수학 문제 이미지 URL")
    student_level_md: str = Field(
        ...,
        min_length=1,
        description="현재 학생 진도 수준을 설명하는 Markdown 문자열",
    )
    curriculum_md: str | None = Field(
        None,
        description="선택. 없으면 curriculum/2022-middle-school-math.md를 사용",
    )
    model: str | None = Field(None, description="선택. 기본값은 GEMINI_MODEL 또는 gemini-2.5-flash")


class GeminiMathSolution(BaseModel):
    problem_text: str | None = Field(None, description="이미지에서 읽은 문제")
    detected_grade_level: str | None = Field(None, description="추정 학년/진도")
    detected_topic: str | None = Field(None, description="문제의 주요 단원")
    used_concepts: list[str] = Field(default_factory=list)
    solution_markdown: str = Field(..., description="학생 눈높이에 맞춘 풀이")
    answer: str | None = Field(None, description="최종 답")
    student_level_notes: str | None = Field(None, description="진도 수준을 고려한 설명 메모")
    missing_concepts: list[str] = Field(default_factory=list)
    recommended_review_units: list[str] = Field(default_factory=list)
    confidence: float = Field(..., ge=0, le=1)
    needs_human_check: bool = False


class SolveResponse(BaseModel):
    model: str
    image_source: str
    image_url: str | None = None
    image_filename: str | None = None
    image_mime_type: str
    result: GeminiMathSolution | dict[str, Any]
    raw_text: str | None = None


app = FastAPI(
    title="Math Tutor Gemini API",
    description="이미지 URL 또는 업로드 파일과 학생 진도 Markdown을 받아 Gemini로 수학 문제를 풀이합니다.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ALLOW_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "model": DEFAULT_MODEL,
        "has_gemini_api_key": bool(os.getenv("GEMINI_API_KEY")),
        "curriculum_dir": str(DEFAULT_CURRICULUM_DIR),
        "curriculum_files": [str(path) for path in find_curriculum_files()],
    }


@app.post("/solve", response_model=SolveResponse)
async def solve(request: SolveRequest) -> SolveResponse:
    curriculum_md = request.curriculum_md or load_default_curriculum()
    image = await download_image(str(request.image_url))
    result = await ask_gemini_for_solution(
        image_bytes=image["bytes"],
        image_mime_type=image["mime_type"],
        image_reference=str(request.image_url),
        student_level_md=request.student_level_md,
        curriculum_md=curriculum_md,
        model=request.model or DEFAULT_MODEL,
    )
    return SolveResponse(
        model=request.model or DEFAULT_MODEL,
        image_source="url",
        image_url=str(request.image_url),
        image_mime_type=image["mime_type"],
        result=result["parsed"],
        raw_text=result["raw_text"],
    )


@app.post("/solve-form", response_model=SolveResponse)
async def solve_form(
    image_url: str | None = Form(None),
    image_file: UploadFile | None = File(None),
    student_level_md: str | None = Form(None),
    student_level_file: UploadFile | None = File(None),
    model: str | None = Form(None),
) -> SolveResponse:
    level_md = student_level_md
    if student_level_file is not None:
        level_md = (await student_level_file.read()).decode("utf-8")
    if not level_md or not level_md.strip():
        raise HTTPException(
            status_code=400,
            detail="student_level_md 또는 student_level_file 중 하나가 필요합니다.",
        )

    if bool(image_url) == bool(image_file):
        raise HTTPException(
            status_code=400,
            detail="image_url 또는 image_file 중 하나만 보내주세요.",
        )

    if image_url:
        return await solve(
            SolveRequest(
                image_url=image_url,
                student_level_md=level_md,
                model=model,
            )
        )

    assert image_file is not None
    curriculum_md = load_default_curriculum()
    image = await read_uploaded_image(image_file)
    result = await ask_gemini_for_solution(
        image_bytes=image["bytes"],
        image_mime_type=image["mime_type"],
        image_reference=f"uploaded file: {image['filename']}",
        student_level_md=level_md,
        curriculum_md=curriculum_md,
        model=model or DEFAULT_MODEL,
    )
    return SolveResponse(
        model=model or DEFAULT_MODEL,
        image_source="upload",
        image_filename=image["filename"],
        image_mime_type=image["mime_type"],
        result=result["parsed"],
        raw_text=result["raw_text"],
    )


def load_default_curriculum() -> str:
    paths = find_curriculum_files()
    if not paths:
        raise HTTPException(
            status_code=500,
            detail=f"기본 교육과정 파일을 찾을 수 없습니다: {DEFAULT_CURRICULUM_DIR}",
        )
    sections = []
    for path in paths:
        sections.append(f"<!-- source: {path.name} -->\n\n{path.read_text(encoding='utf-8')}")
    return "\n\n---\n\n".join(sections)


def find_curriculum_files() -> list[Path]:
    if not DEFAULT_CURRICULUM_DIR.exists():
        return []
    return sorted(DEFAULT_CURRICULUM_DIR.glob("*.md"))


async def download_image(image_url: str) -> dict[str, Any]:
    assert_public_http_url(image_url)

    timeout = httpx.Timeout(20.0, connect=8.0)
    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
        try:
            response = await client.get(image_url)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"이미지 URL 응답 오류: HTTP {exc.response.status_code}",
            ) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"이미지 URL을 내려받을 수 없습니다: {exc}",
            ) from exc

    if len(response.content) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"이미지가 너무 큽니다. 최대 {MAX_IMAGE_BYTES} bytes까지 허용합니다.",
        )

    mime_type = normalize_image_mime_type(
        response.headers.get("content-type"),
        image_url,
    )
    return {"bytes": response.content, "mime_type": mime_type}


async def read_uploaded_image(image_file: UploadFile) -> dict[str, Any]:
    filename = image_file.filename or "uploaded-image"
    content = await image_file.read()

    if not content:
        raise HTTPException(status_code=400, detail="업로드된 이미지 파일이 비어 있습니다.")
    if len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"이미지가 너무 큽니다. 최대 {MAX_IMAGE_BYTES} bytes까지 허용합니다.",
        )

    mime_type = normalize_image_mime_type(image_file.content_type, filename)
    return {"bytes": content, "mime_type": mime_type, "filename": filename}


def normalize_image_mime_type(content_type: str | None, source_name: str) -> str:
    if content_type:
        mime_type = content_type.split(";")[0].strip().lower()
        if mime_type.startswith("image/"):
            return mime_type

    guessed_mime_type, _ = mimetypes.guess_type(urlparse(source_name).path or source_name)
    if guessed_mime_type and guessed_mime_type.startswith("image/"):
        return guessed_mime_type

    raise HTTPException(
        status_code=400,
        detail="이미지 MIME type을 확인할 수 없습니다. jpeg/png/webp 등 이미지 파일을 사용해주세요.",
    )


def assert_public_http_url(raw_url: str) -> None:
    parsed = urlparse(raw_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(status_code=400, detail="http 또는 https 이미지 URL이 필요합니다.")

    if ALLOW_PRIVATE_IMAGE_URLS:
        return

    try:
        addresses = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror as exc:
        raise HTTPException(status_code=400, detail="이미지 URL의 호스트를 확인할 수 없습니다.") from exc

    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    "보안을 위해 private/localhost 이미지 URL은 기본 차단됩니다. "
                    "로컬 테스트가 필요하면 ALLOW_PRIVATE_IMAGE_URLS=true를 설정하세요."
                ),
            )


async def ask_gemini_for_solution(
    *,
    image_bytes: bytes,
    image_mime_type: str,
    image_reference: str,
    student_level_md: str,
    curriculum_md: str,
    model: str,
) -> dict[str, Any]:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="GEMINI_API_KEY 환경변수가 설정되어 있지 않습니다.",
        )

    prompt = build_prompt(
        image_reference=image_reference,
        student_level_md=student_level_md,
        curriculum_md=curriculum_md,
    )

    try:
        async with genai.Client(api_key=api_key).aio as client:
            response = await client.models.generate_content(
                model=model,
                contents=[
                    types.Part.from_text(text=prompt),
                    types.Part.from_bytes(data=image_bytes, mime_type=image_mime_type),
                ],
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    temperature=0.2,
                    response_mime_type="application/json",
                    response_schema=GeminiMathSolution,
                ),
            )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Gemini 호출 실패: {exc}") from exc

    return {
        "parsed": parse_gemini_response(response),
        "raw_text": response.text,
    }


def build_prompt(*, image_reference: str, student_level_md: str, curriculum_md: str) -> str:
    return f"""
아래 수학 문제 이미지를 읽고, 학생의 현재 진도 수준에 맞춰 풀이해줘.

요구사항:
- 이미지에서 문제를 먼저 정확히 읽어라.
- 학생이 아직 배우지 않은 개념은 기본 풀이에 사용하지 마라.
- 필요한 경우 이전 단원 개념을 짧게 복습하고 풀이를 이어가라.
- 풀이 과정을 Markdown으로 작성하라.
- 오답노트 저장을 위해 부족한 개념과 추천 복습 단원을 구체적으로 적어라.
- 이미지가 흐리거나 조건 일부를 확신할 수 없으면 `needs_human_check=true`로 표시하라.

이미지 출처:
{image_reference}

학생 현재 진도 Markdown:
```markdown
{student_level_md}
```

교육과정 Markdown:
```markdown
{curriculum_md}
```
""".strip()


def parse_gemini_response(response: Any) -> GeminiMathSolution | dict[str, Any]:
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, GeminiMathSolution):
        return parsed
    if hasattr(parsed, "model_dump"):
        return parsed.model_dump()
    if parsed is not None:
        return parsed

    text = getattr(response, "text", "") or ""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {
            "solution_markdown": text,
            "confidence": 0,
            "needs_human_check": True,
            "used_concepts": [],
            "missing_concepts": [],
            "recommended_review_units": [],
        }
