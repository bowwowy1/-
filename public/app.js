const state = { project: null, pollTimer: null };

const $ = (sel) => document.querySelector(sel);

async function api(path, options) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `요청 실패 (${res.status})`);
  return data;
}

function setProject(project) {
  state.project = project;
  render();
  if (project && project.status === 'generating') {
    startPolling();
  } else {
    stopPolling();
  }
}

function startPolling() {
  stopPolling();
  state.pollTimer = setInterval(async () => {
    try {
      const project = await api(`/api/projects/${state.project.id}`);
      state.project = project;
      renderGenerateList();
      if (project.status !== 'generating') stopPolling();
    } catch (e) {
      console.error(e);
    }
  }, 4000);
}

function stopPolling() {
  if (state.pollTimer) clearInterval(state.pollTimer);
  state.pollTimer = null;
}

function render() {
  const p = state.project;
  $('#script-section').classList.toggle('hidden', !p);
  $('#storyboard-section').classList.toggle('hidden', !p || !p.cuts || p.cuts.length === 0);
  $('#generate-section').classList.toggle('hidden', !p || !['storyboard_confirmed', 'generating', 'completed'].includes(p.status));

  if (!p) return;

  $('#script-text').value = p.script || '';
  renderCutsList();
  renderGenerateList();

  const locked = p.status === 'storyboard_confirmed' || p.status === 'generating' || p.status === 'completed';
  $('#add-cut-btn').disabled = locked;
  $('#confirm-storyboard-btn').disabled = locked;
}

function statusLabel(status) {
  return {
    pending: '대기중',
    image_generating: '이미지 생성중...',
    video_generating: '영상 생성중...',
    video_done: '완료',
    failed: '실패',
  }[status] || status;
}

function renderCutsList() {
  const p = state.project;
  const container = $('#cuts-list');
  container.innerHTML = '';
  const locked = p.status === 'storyboard_confirmed' || p.status === 'generating' || p.status === 'completed';

  p.cuts.forEach((cut) => {
    const div = document.createElement('div');
    div.className = 'cut-card';
    div.innerHTML = `
      <div class="cut-header">
        <strong>컷 ${cut.index + 1}</strong>
        <button class="danger delete-cut-btn" ${locked ? 'disabled' : ''}>삭제</button>
      </div>
      <label>장면 설명</label>
      <textarea rows="2" class="scene-desc" ${locked ? 'disabled' : ''}>${escapeHtml(cut.sceneDescription)}</textarea>
      <label>이미지 프롬프트 (영어)</label>
      <textarea rows="2" class="image-prompt" ${locked ? 'disabled' : ''}>${escapeHtml(cut.imagePrompt)}</textarea>
      <div class="duration-row">
        <label style="margin:0;">길이(초)</label>
        <input type="number" class="duration" value="${cut.durationSec}" min="1" max="30" ${locked ? 'disabled' : ''} />
      </div>
    `;

    const sceneEl = div.querySelector('.scene-desc');
    const promptEl = div.querySelector('.image-prompt');
    const durEl = div.querySelector('.duration');
    const saveEdit = debounce(async () => {
      try {
        await api(`/api/projects/${p.id}/cuts/${cut.id}`, {
          method: 'PUT',
          body: JSON.stringify({
            sceneDescription: sceneEl.value,
            imagePrompt: promptEl.value,
            durationSec: Number(durEl.value) || 8,
          }),
        });
      } catch (e) {
        $('#storyboard-status').textContent = '오류: ' + e.message;
      }
    }, 500);
    sceneEl.addEventListener('input', saveEdit);
    promptEl.addEventListener('input', saveEdit);
    durEl.addEventListener('input', saveEdit);

    div.querySelector('.delete-cut-btn').addEventListener('click', async () => {
      const project = await api(`/api/projects/${p.id}/cuts/${cut.id}`, { method: 'DELETE' });
      setProject(project);
    });

    container.appendChild(div);
  });
}

function renderGenerateList() {
  const p = state.project;
  const container = $('#generate-list');
  container.innerHTML = '';
  if (!p.cuts) return;

  p.cuts.forEach((cut) => {
    const div = document.createElement('div');
    div.className = 'cut-card';
    let media = '';
    if (cut.imagePath) media += `<img src="${cut.imagePath}" alt="컷 ${cut.index + 1} 이미지" />`;
    if (cut.videoPath) media += `<video controls src="${cut.videoPath}"></video>`;

    div.innerHTML = `
      <div class="cut-header">
        <strong>컷 ${cut.index + 1}</strong>
        <span class="status-badge status-${cut.status}">${statusLabel(cut.status)}</span>
      </div>
      <div>${escapeHtml(cut.sceneDescription)}</div>
      <div class="media-preview">${media}</div>
      ${cut.error ? `<div class="error-text">${escapeHtml(cut.error)}</div>` : ''}
      ${cut.videoPath ? `<div class="row"><a href="${cut.videoPath}" download><button>mp4 다운로드</button></a></div>` : ''}
    `;
    container.appendChild(div);
  });
}

function escapeHtml(str) {
  return String(str || '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function debounce(fn, ms) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}

$('#create-project-btn').addEventListener('click', async () => {
  const topic = $('#topic-input').value.trim();
  if (!topic) return;
  $('#topic-status').textContent = '대본 생성 중...';
  $('#create-project-btn').disabled = true;
  try {
    const project = await api('/api/projects', { method: 'POST', body: JSON.stringify({ topic }) });
    setProject(project);
    $('#topic-status').textContent = '';
  } catch (e) {
    $('#topic-status').textContent = '오류: ' + e.message;
  } finally {
    $('#create-project-btn').disabled = false;
  }
});

$('#save-script-btn').addEventListener('click', async () => {
  try {
    const project = await api(`/api/projects/${state.project.id}/script`, {
      method: 'PUT',
      body: JSON.stringify({ script: $('#script-text').value }),
    });
    setProject(project);
    $('#script-status').textContent = '저장됨';
  } catch (e) {
    $('#script-status').textContent = '오류: ' + e.message;
  }
});

$('#regen-script-btn').addEventListener('click', async () => {
  $('#script-status').textContent = '재생성 중...';
  try {
    const project = await api(`/api/projects/${state.project.id}/script/regenerate`, { method: 'POST' });
    setProject(project);
    $('#script-status').textContent = '';
  } catch (e) {
    $('#script-status').textContent = '오류: ' + e.message;
  }
});

$('#make-storyboard-btn').addEventListener('click', async () => {
  $('#script-status').textContent = '스토리보드 생성 중...';
  try {
    const project = await api(`/api/projects/${state.project.id}/storyboard`, { method: 'POST' });
    setProject(project);
    $('#script-status').textContent = '';
  } catch (e) {
    $('#script-status').textContent = '오류: ' + e.message;
  }
});

$('#add-cut-btn').addEventListener('click', async () => {
  const project = await api(`/api/projects/${state.project.id}/cuts`, {
    method: 'POST',
    body: JSON.stringify({ sceneDescription: '', imagePrompt: '', durationSec: 8 }),
  });
  setProject(project);
});

$('#confirm-storyboard-btn').addEventListener('click', async () => {
  try {
    const project = await api(`/api/projects/${state.project.id}/confirm`, { method: 'POST' });
    setProject(project);
    $('#storyboard-status').textContent = '';
  } catch (e) {
    $('#storyboard-status').textContent = '오류: ' + e.message;
  }
});

$('#unlock-btn').addEventListener('click', async () => {
  const project = await api(`/api/projects/${state.project.id}/unlock`, { method: 'POST' });
  setProject(project);
});

$('#start-generate-btn').addEventListener('click', async () => {
  await api(`/api/projects/${state.project.id}/generate`, { method: 'POST' });
  const project = await api(`/api/projects/${state.project.id}`);
  setProject(project);
});
