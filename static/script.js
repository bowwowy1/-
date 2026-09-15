const topicInput = document.getElementById("topic-input");
const generateBtn = document.getElementById("generate-btn");
const progressWrap = document.getElementById("progress-wrap");
const progressStage = document.getElementById("progress-stage");
const progressBarInner = document.getElementById("progress-bar-inner");
const progressPercent = document.getElementById("progress-percent");
const errorBox = document.getElementById("error-box");
const previewVideo = document.getElementById("preview-video");
const previewPlaceholder = document.getElementById("preview-placeholder");
const downloadLink = document.getElementById("download-link");

let pollTimer = null;

function resetUI() {
  errorBox.classList.add("hidden");
  errorBox.textContent = "";
  downloadLink.classList.add("hidden");
  previewVideo.style.display = "none";
  previewPlaceholder.style.display = "block";
  progressWrap.classList.remove("hidden");
  progressBarInner.style.width = "0%";
  progressPercent.textContent = "0%";
  progressStage.textContent = "대기 중";
}

function setError(message) {
  errorBox.textContent = message;
  errorBox.classList.remove("hidden");
  generateBtn.disabled = false;
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

    if (data.status === "error") {
      clearInterval(pollTimer);
      setError(`[${data.stage}] ${data.error}`);
      return;
    }

    if (data.status === "done") {
      clearInterval(pollTimer);
      generateBtn.disabled = false;
      previewVideo.src = data.download_url;
      previewVideo.style.display = "block";
      previewPlaceholder.style.display = "none";
      downloadLink.href = data.download_url;
      downloadLink.classList.remove("hidden");
    }
  }, 2000);
}

generateBtn.addEventListener("click", startGeneration);
topicInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") startGeneration();
});
