const topicInput = document.getElementById("topic-input");
const generateBtn = document.getElementById("generate-btn");
const progressWrap = document.getElementById("progress-wrap");
const progressStage = document.getElementById("progress-stage");
const progressBarInner = document.getElementById("progress-bar-inner");
const progressPercent = document.getElementById("progress-percent");
const errorBox = document.getElementById("error-box");
const downloadLink = document.getElementById("download-link");
const scriptBox = document.getElementById("script-box");
const scriptTitle = document.getElementById("script-title");
const scriptFull = document.getElementById("script-full");
const narrationAudio = document.getElementById("narration-audio");
const sceneGrid = document.getElementById("scene-grid");

let pollTimer = null;
const renderedScenes = new Set();

function resetUI() {
  errorBox.classList.add("hidden");
  errorBox.textContent = "";
  downloadLink.classList.add("hidden");
  progressWrap.classList.remove("hidden");
  progressBarInner.style.width = "0%";
  progressPercent.textContent = "0%";
  progressStage.textContent = "대기 중";
  scriptBox.classList.add("hidden");
  scriptTitle.textContent = "";
  scriptFull.textContent = "";
  narrationAudio.classList.add("hidden");
  narrationAudio.removeAttribute("src");
  sceneGrid.innerHTML = "";
  renderedScenes.clear();
}

function setError(message) {
  errorBox.textContent = message;
  errorBox.classList.remove("hidden");
  generateBtn.disabled = false;
}

function renderScene(scene) {
  if (renderedScenes.has(scene.cut_no)) return;
  renderedScenes.add(scene.cut_no);

  const card = document.createElement("div");
  card.className = "scene-card";
  card.innerHTML = `
    <video src="${scene.video_url}" muted loop playsinline preload="metadata"
      onmouseover="this.play()" onmouseout="this.pause()"></video>
    <div class="scene-body">
      <div class="scene-no">CUT ${String(scene.cut_no).padStart(2, "0")} · ${scene.section}</div>
      <div class="scene-narration">${scene.narration}</div>
      <div class="scene-links">
        <a href="${scene.image_url}" download target="_blank" rel="noopener">이미지</a>
        <a href="${scene.video_url}" download target="_blank" rel="noopener">영상</a>
      </div>
    </div>
  `;
  sceneGrid.appendChild(card);
}

async function startGeneration() {
  const topic = topicInput.value.trim();
  if (!topic) {
    setError("주제를 입력해주세요.");
    return;
  }

  resetUI();
  generateBtn.disabled = true;

  let res;
  try {
    res = await fetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ topic }),
    });
  } catch (e) {
    setError("서버에 연결할 수 없습니다: " + e.message);
    return;
  }

  const data = await res.json().catch(() => ({}));

  if (!res.ok) {
    setError(data.error || "생성 요청에 실패했습니다.");
    return;
  }

  pollStatus(data.job_id);
}

function pollStatus(jobId) {
  if (pollTimer) clearInterval(pollTimer);

  pollTimer = setInterval(async () => {
    let res;
    try {
      res = await fetch(`/api/status/${jobId}`);
    } catch (e) {
      return; // 일시적 네트워크 오류는 다음 폴링에서 재시도
    }

    const data = await res.json().catch(() => null);
    if (!res.ok || !data) {
      clearInterval(pollTimer);
      setError((data && data.error) || "상태 조회에 실패했습니다.");
      return;
    }

    progressStage.textContent = data.stage || "";
    progressBarInner.style.width = `${data.progress || 0}%`;
    progressPercent.textContent = `${data.progress || 0}%`;

    if (data.title) {
      scriptBox.classList.remove("hidden");
      scriptTitle.textContent = data.title;
      scriptFull.textContent = data.full_script || "";
    }

    (data.scenes || []).forEach(renderScene);

    if (data.status === "error") {
      clearInterval(pollTimer);
      setError(`[${data.stage}] ${data.error}`);
      return;
    }

    if (data.status === "done") {
      clearInterval(pollTimer);
      generateBtn.disabled = false;
      narrationAudio.src = `/api/media/${jobId}/narration.mp3`;
      narrationAudio.classList.remove("hidden");
      downloadLink.href = data.zip_url;
      downloadLink.classList.remove("hidden");
    }
  }, 2000);
}

generateBtn.addEventListener("click", startGeneration);
topicInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") startGeneration();
});
