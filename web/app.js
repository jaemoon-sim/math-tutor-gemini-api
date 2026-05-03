const STORAGE_KEY = "mathTutorDemoProfiles";

const state = {
  profiles: [],
  selectedId: "",
  imageFile: null,
  imageUrl: "",
  lastResponse: null,
};

const els = {
  profileSelect: document.querySelector("#profile-select"),
  profileMeta: document.querySelector("#profile-meta"),
  profileForm: document.querySelector("#profile-form"),
  profileName: document.querySelector("#profile-name"),
  profileMd: document.querySelector("#profile-md"),
  deleteProfile: document.querySelector("#delete-profile"),
  resetProfiles: document.querySelector("#reset-profiles"),
  solveForm: document.querySelector("#solve-form"),
  imageFile: document.querySelector("#image-file"),
  fileLabel: document.querySelector("#file-label"),
  imagePreview: document.querySelector("#image-preview"),
  solveButton: document.querySelector("#solve-button"),
  statusLine: document.querySelector("#status-line"),
  summaryTopic: document.querySelector("#summary-topic"),
  summaryConfidence: document.querySelector("#summary-confidence"),
  summaryCheck: document.querySelector("#summary-check"),
  tabSolution: document.querySelector("#tab-solution"),
  tabNotebook: document.querySelector("#tab-notebook"),
  tabRaw: document.querySelector("#tab-raw"),
  rawOutput: document.querySelector(".json-output"),
  tabs: document.querySelectorAll(".tab"),
  panels: document.querySelectorAll(".tab-panel"),
};

init();

async function init() {
  bindEvents();
  await loadProfiles();
  renderProfiles();
}

function bindEvents() {
  els.profileSelect.addEventListener("change", () => {
    state.selectedId = els.profileSelect.value;
    renderSelectedProfile();
  });

  els.profileForm.addEventListener("submit", (event) => {
    event.preventDefault();
    saveProfile();
  });

  els.deleteProfile.addEventListener("click", deleteSelectedProfile);
  els.resetProfiles.addEventListener("click", resetProfiles);
  els.imageFile.addEventListener("change", handleImageChange);
  els.solveForm.addEventListener("submit", solveProblem);

  els.tabs.forEach((tab) => {
    tab.addEventListener("click", () => activateTab(tab.dataset.tab));
  });
}

async function loadProfiles() {
  const stored = readStoredProfiles();
  if (stored.length > 0) {
    state.profiles = stored;
    state.selectedId = stored[0].id;
    return;
  }

  const sampleProfiles = await fetchSampleProfiles();
  state.profiles = sampleProfiles;
  state.selectedId = sampleProfiles[0]?.id || "";
  writeStoredProfiles();
}

function readStoredProfiles() {
  try {
    const parsed = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

async function fetchSampleProfiles() {
  try {
    const response = await fetch("/sample-levels");
    if (!response.ok) return [];
    const samples = await response.json();
    return samples.map((sample) => ({
      id: `sample:${sample.id}`,
      name: sample.name,
      markdown: sample.markdown,
      source: "sample",
    }));
  } catch {
    return [];
  }
}

function writeStoredProfiles() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state.profiles));
}

async function resetProfiles() {
  const samples = await fetchSampleProfiles();
  state.profiles = samples;
  state.selectedId = samples[0]?.id || "";
  writeStoredProfiles();
  renderProfiles();
  setStatus("기본 진도현황을 불러왔습니다.");
}

function renderProfiles() {
  els.profileSelect.innerHTML = "";
  state.profiles.forEach((profile) => {
    const option = document.createElement("option");
    option.value = profile.id;
    option.textContent = profile.name;
    els.profileSelect.append(option);
  });

  if (!state.selectedId && state.profiles[0]) {
    state.selectedId = state.profiles[0].id;
  }
  els.profileSelect.value = state.selectedId;
  renderSelectedProfile();
}

function renderSelectedProfile() {
  const profile = selectedProfile();
  if (!profile) {
    els.profileName.value = "";
    els.profileMd.value = "";
    els.profileMeta.textContent = "저장된 진도현황 없음";
    return;
  }

  els.profileName.value = profile.name;
  els.profileMd.value = profile.markdown;
  els.profileMeta.textContent = `${profile.markdown.length.toLocaleString()}자`;
}

function saveProfile() {
  const name = els.profileName.value.trim();
  const markdown = els.profileMd.value.trim();

  if (!name || !markdown) {
    setStatus("진도현황 이름과 Markdown을 입력해주세요.", true);
    return;
  }

  const current = selectedProfile();
  const id = current ? current.id : `profile:${crypto.randomUUID()}`;
  const nextProfile = {
    id,
    name,
    markdown,
    source: current?.source === "sample" ? "edited" : current?.source || "custom",
  };

  const index = state.profiles.findIndex((profile) => profile.id === id);
  if (index >= 0) {
    state.profiles[index] = nextProfile;
  } else {
    state.profiles.unshift(nextProfile);
  }

  state.selectedId = id;
  writeStoredProfiles();
  renderProfiles();
  setStatus("진도현황을 저장했습니다.");
}

function deleteSelectedProfile() {
  if (!state.selectedId) return;
  state.profiles = state.profiles.filter((profile) => profile.id !== state.selectedId);
  state.selectedId = state.profiles[0]?.id || "";
  writeStoredProfiles();
  renderProfiles();
  setStatus("진도현황을 삭제했습니다.");
}

function selectedProfile() {
  return state.profiles.find((profile) => profile.id === state.selectedId);
}

function handleImageChange() {
  const file = els.imageFile.files?.[0];
  state.imageFile = file || null;

  if (!file) {
    state.imageUrl = "";
    els.fileLabel.textContent = "이미지 선택";
    els.imagePreview.innerHTML = "<span>선택된 이미지 없음</span>";
    return;
  }

  if (state.imageUrl) URL.revokeObjectURL(state.imageUrl);
  state.imageUrl = URL.createObjectURL(file);
  els.fileLabel.textContent = file.name;
  els.imagePreview.innerHTML = "";
  const image = document.createElement("img");
  image.src = state.imageUrl;
  image.alt = file.name;
  els.imagePreview.append(image);
}

async function solveProblem(event) {
  event.preventDefault();
  const profile = selectedProfile();

  if (!profile) {
    setStatus("진도현황을 선택해주세요.", true);
    return;
  }

  if (!state.imageFile) {
    setStatus("문제 이미지를 선택해주세요.", true);
    return;
  }

  const formData = new FormData();
  formData.append("image_file", state.imageFile);
  formData.append("student_level_md", profile.markdown);

  setLoading(true);
  try {
    const response = await fetch("/solve-form", {
      method: "POST",
      body: formData,
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "풀이 요청에 실패했습니다.");
    }
    state.lastResponse = data;
    renderResult(data);
    setStatus("풀이 완료");
  } catch (error) {
    setStatus(error.message || "풀이 요청에 실패했습니다.", true);
  } finally {
    setLoading(false);
  }
}

function renderResult(response) {
  const result = response.result || {};
  els.summaryTopic.textContent = result.detected_topic || "-";
  els.summaryConfidence.textContent =
    typeof result.confidence === "number" ? `${Math.round(result.confidence * 100)}%` : "-";
  els.summaryCheck.textContent = result.needs_human_check ? "예" : "아니오";

  const solutionParts = [];
  if (result.needs_human_check) {
    solutionParts.push('<div class="notice">이미지 또는 조건 확인이 필요합니다.</div>');
  }
  if (result.problem_text) {
    solutionParts.push(`<h2>읽은 문제</h2>${markdownToHtml(result.problem_text)}`);
  }
  if (result.answer) {
    solutionParts.push(`<h2>답</h2>${markdownToHtml(result.answer)}`);
  }
  solutionParts.push(`<h2>풀이</h2>${markdownToHtml(result.solution_markdown || "")}`);
  els.tabSolution.innerHTML = solutionParts.join("");

  els.tabNotebook.innerHTML = renderNotebook(result);
  els.rawOutput.textContent = JSON.stringify(response, null, 2);
  activateTab("solution");
}

function renderNotebook(result) {
  const sections = [
    ["사용한 개념", result.used_concepts],
    ["부족한 개념", result.missing_concepts],
    ["추천 복습 단원", result.recommended_review_units],
  ];

  const html = [];
  if (result.detected_grade_level || result.student_level_notes) {
    html.push("<h2>진도 메모</h2>");
    if (result.detected_grade_level) html.push(`<p>${escapeHtml(result.detected_grade_level)}</p>`);
    if (result.student_level_notes) html.push(markdownToHtml(result.student_level_notes));
  }

  sections.forEach(([title, items]) => {
    html.push(`<h2>${title}</h2>`);
    html.push(renderPills(items));
  });

  return html.join("");
}

function renderPills(items) {
  if (!Array.isArray(items) || items.length === 0) {
    return '<p class="empty-copy">-</p>';
  }
  return `<div class="pill-list">${items.map((item) => `<span class="pill">${escapeHtml(item)}</span>`).join("")}</div>`;
}

function markdownToHtml(markdown) {
  const lines = String(markdown || "").split("\n");
  const html = [];
  let listOpen = false;

  lines.forEach((line) => {
    const trimmed = line.trim();
    if (!trimmed) {
      if (listOpen) {
        html.push("</ul>");
        listOpen = false;
      }
      return;
    }

    const heading = trimmed.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      if (listOpen) {
        html.push("</ul>");
        listOpen = false;
      }
      html.push(`<h${heading[1].length}>${inlineMarkdown(heading[2])}</h${heading[1].length}>`);
      return;
    }

    const bullet = trimmed.match(/^[-*]\s+(.+)$/);
    if (bullet) {
      if (!listOpen) {
        html.push("<ul>");
        listOpen = true;
      }
      html.push(`<li>${inlineMarkdown(bullet[1])}</li>`);
      return;
    }

    if (listOpen) {
      html.push("</ul>");
      listOpen = false;
    }
    html.push(`<p>${inlineMarkdown(trimmed)}</p>`);
  });

  if (listOpen) html.push("</ul>");
  return html.join("");
}

function inlineMarkdown(text) {
  return escapeHtml(text)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/`(.+?)`/g, "<code>$1</code>");
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function activateTab(name) {
  els.tabs.forEach((tab) => tab.classList.toggle("active", tab.dataset.tab === name));
  els.panels.forEach((panel) => panel.classList.toggle("active", panel.id === `tab-${name}`));
}

function setLoading(isLoading) {
  els.solveButton.disabled = isLoading;
  els.solveButton.textContent = isLoading ? "풀이 중" : "풀이 요청";
  if (isLoading) setStatus("풀이 중");
}

function setStatus(message, isError = false) {
  els.statusLine.textContent = message;
  els.statusLine.style.color = isError ? "var(--danger)" : "var(--muted)";
}
