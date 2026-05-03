# Math Tutor Gemini API

이미지 URL 또는 업로드 파일과 학생 현재 진도 Markdown을 받아 Gemini로 수학 문제 풀이를 요청하는 작은 FastAPI 서버다.

## 준비

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

`.env`에 `GEMINI_API_KEY`를 넣는다.

## 실행

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

## Health Check

```bash
curl http://127.0.0.1:8000/health
```

기본 교육과정 맥락은 `curriculum/*.md` 파일을 파일명 순서대로 합쳐서 Gemini 프롬프트에 넣는다. 특정 요청에서 `curriculum_md`를 직접 보내면 그 값을 우선 사용한다.

## 문제 풀이 요청

```bash
curl -X POST http://127.0.0.1:8000/solve \
  -H "Content-Type: application/json" \
  -d '{
    "image_url": "https://example.com/math-problem.png",
    "student_level_md": "# 현재 진도\n\n- 학년: 중학교 2학년\n- 현재 단원: 피타고라스 정리까지 완료\n- 아직 배우지 않음: 제곱근과 실수, 이차방정식, 삼각비"
  }'
```

Markdown 파일을 그대로 업로드하려면 multipart 엔드포인트도 쓸 수 있다. 이미지도 URL 대신 파일로 보낼 수 있다.

```bash
curl -X POST http://127.0.0.1:8000/solve-form \
  -F "image_url=https://example.com/math-problem.png" \
  -F "student_level_file=@student-level.md"
```

```bash
curl -X POST http://127.0.0.1:8000/solve-form \
  -F "image_file=@math-problem.png" \
  -F "student_level_file=@samples/middle-2-student-level.md"
```

`/solve-form`에서는 `image_url` 또는 `image_file` 중 하나만 보내야 한다.

## 응답 구조

```json
{
  "model": "gemini-2.5-flash",
  "image_source": "url",
  "image_url": "https://example.com/math-problem.png",
  "image_filename": null,
  "image_mime_type": "image/png",
  "result": {
    "problem_text": "...",
    "detected_grade_level": "중학교 2학년",
    "detected_topic": "연립일차방정식",
    "used_concepts": ["가감법", "일차방정식"],
    "solution_markdown": "...",
    "answer": "...",
    "missing_concepts": ["일차방정식의 이항"],
    "recommended_review_units": ["중1 일차방정식", "중2 연립일차방정식"],
    "confidence": 0.9,
    "needs_human_check": false
  }
}
```
