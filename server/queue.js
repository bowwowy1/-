const path = require('path');
const fs = require('fs');
const db = require('./db');
const imagen = require('./providers/imagen');
const veo = require('./providers/veo');
const { DATA_DIR } = db;

const STORAGE_DIR = path.join(__dirname, '..', 'storage');

function cutDir(projectId) {
  const dir = path.join(STORAGE_DIR, projectId);
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
  return dir;
}

function setCutStatus(projectId, cutId, patch) {
  return db.mutate((data) => {
    const project = data.projects[projectId];
    if (!project) return;
    const cut = project.cuts.find((c) => c.id === cutId);
    if (!cut) return;
    Object.assign(cut, patch);
    project.updatedAt = new Date().toISOString();
  });
}

async function processCut(projectId, cut) {
  const dir = cutDir(projectId);
  try {
    await setCutStatus(projectId, cut.id, { status: 'image_generating', error: null });
    const image = await imagen.generateImage(cut.imagePrompt);
    const ext = image.mimeType.includes('png') ? 'png' : 'jpg';
    const imageFile = path.join(dir, `cut-${cut.index}.${ext}`);
    imagen.saveImage(image.buffer, imageFile);
    await setCutStatus(projectId, cut.id, {
      status: 'video_generating',
      imagePath: `/storage/${projectId}/${path.basename(imageFile)}`,
    });

    const videoBuffer = await veo.generateVideoFromImage(image.buffer, image.mimeType, cut.imagePrompt);
    const videoFile = path.join(dir, `cut-${cut.index}.mp4`);
    veo.saveVideo(videoBuffer, videoFile);
    await setCutStatus(projectId, cut.id, {
      status: 'video_done',
      videoPath: `/storage/${projectId}/${path.basename(videoFile)}`,
    });
  } catch (err) {
    await setCutStatus(projectId, cut.id, { status: 'failed', error: err.message });
  }
}

// 전체 앱에서 하나씩 순차 처리 (API 레이트리밋 보호용 단순 큐)
let chain = Promise.resolve();

function enqueueProjectGeneration(projectId) {
  chain = chain.then(async () => {
    const project = db.getProject(projectId);
    if (!project) return;
    for (const cut of project.cuts) {
      if (cut.status === 'video_done') continue; // 이미 완료된 컷은 재생성하지 않음
      await processCut(projectId, cut);
    }
    await db.mutate((data) => {
      const p = data.projects[projectId];
      if (p) p.status = 'completed';
    });
  });
  return chain;
}

module.exports = { enqueueProjectGeneration };
