require('dotenv').config();
const express = require('express');
const path = require('path');
const { v4: uuidv4 } = require('uuid');

const db = require('./db');
const { callGemini } = require('./providers/geminiText');
const { scriptPrompt, storyboardPrompt } = require('./prompts');
const { enqueueProjectGeneration } = require('./queue');

const app = express();
app.use(express.json());
app.use(express.static(path.join(__dirname, '..', 'public')));
app.use('/storage', express.static(path.join(__dirname, '..', 'storage')));

function projectSummary(project) {
  return project; // 현재는 그대로 노출 (내부 필드 없음)
}

// 1) 주제 -> 대본 생성 -> 프로젝트 생성
app.post('/api/projects', async (req, res) => {
  const { topic } = req.body || {};
  if (!topic || !topic.trim()) return res.status(400).json({ error: 'topic이 필요합니다' });

  try {
    const script = await callGemini(scriptPrompt(topic));
    const id = uuidv4();
    const project = {
      id,
      topic,
      script,
      status: 'script_ready',
      cuts: [],
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };
    await db.mutate((data) => {
      data.projects[id] = project;
    });
    res.json(project);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.get('/api/projects', (req, res) => {
  res.json(Object.values(db.getAll()).sort((a, b) => b.createdAt.localeCompare(a.createdAt)));
});

app.get('/api/projects/:id', (req, res) => {
  const project = db.getProject(req.params.id);
  if (!project) return res.status(404).json({ error: '프로젝트를 찾을 수 없습니다' });
  res.json(projectSummary(project));
});

// 대본 직접 수정
app.put('/api/projects/:id/script', async (req, res) => {
  const { script } = req.body || {};
  if (typeof script !== 'string') return res.status(400).json({ error: 'script가 필요합니다' });
  const project = await db.mutate((data) => {
    const p = data.projects[req.params.id];
    if (!p) return null;
    p.script = script;
    p.updatedAt = new Date().toISOString();
    return p;
  });
  if (!project) return res.status(404).json({ error: '프로젝트를 찾을 수 없습니다' });
  res.json(project);
});

// 대본 재생성
app.post('/api/projects/:id/script/regenerate', async (req, res) => {
  const existing = db.getProject(req.params.id);
  if (!existing) return res.status(404).json({ error: '프로젝트를 찾을 수 없습니다' });
  try {
    const script = await callGemini(scriptPrompt(existing.topic));
    const project = await db.mutate((data) => {
      const p = data.projects[req.params.id];
      p.script = script;
      p.updatedAt = new Date().toISOString();
      return p;
    });
    res.json(project);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// 2) 대본 -> 스토리보드 생성
app.post('/api/projects/:id/storyboard', async (req, res) => {
  const existing = db.getProject(req.params.id);
  if (!existing) return res.status(404).json({ error: '프로젝트를 찾을 수 없습니다' });

  try {
    const raw = await callGemini(storyboardPrompt(existing.topic, existing.script), { json: true });
    let parsed;
    try {
      parsed = JSON.parse(raw);
    } catch {
      const match = raw.match(/\{[\s\S]*\}/);
      if (!match) throw new Error('스토리보드 JSON 파싱 실패: ' + raw.slice(0, 300));
      parsed = JSON.parse(match[0]);
    }

    const cuts = (parsed.cuts || []).map((c, index) => ({
      id: uuidv4(),
      index,
      sceneDescription: c.scene_description || '',
      imagePrompt: c.image_prompt || '',
      durationSec: c.duration_sec || 8,
      status: 'pending',
      imagePath: null,
      videoPath: null,
      error: null,
    }));

    const project = await db.mutate((data) => {
      const p = data.projects[req.params.id];
      p.cuts = cuts;
      p.status = 'storyboard_ready';
      p.updatedAt = new Date().toISOString();
      return p;
    });
    res.json(project);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// 컷 수정
app.put('/api/projects/:id/cuts/:cutId', async (req, res) => {
  const { sceneDescription, imagePrompt, durationSec } = req.body || {};
  const project = await db.mutate((data) => {
    const p = data.projects[req.params.id];
    if (!p) return null;
    if (p.status === 'storyboard_confirmed' || p.status === 'generating' || p.status === 'completed') {
      throw new Error('확정된 스토리보드는 잠금 해제 후 수정하세요');
    }
    const cut = p.cuts.find((c) => c.id === req.params.cutId);
    if (!cut) return null;
    if (sceneDescription !== undefined) cut.sceneDescription = sceneDescription;
    if (imagePrompt !== undefined) cut.imagePrompt = imagePrompt;
    if (durationSec !== undefined) cut.durationSec = durationSec;
    p.updatedAt = new Date().toISOString();
    return p;
  }).catch((err) => {
    res.status(400).json({ error: err.message });
    return undefined;
  });
  if (project === undefined) return; // 에러 응답 이미 전송됨
  if (!project) return res.status(404).json({ error: '프로젝트 또는 컷을 찾을 수 없습니다' });
  res.json(project);
});

// 컷 추가
app.post('/api/projects/:id/cuts', async (req, res) => {
  const { sceneDescription = '', imagePrompt = '', durationSec = 8 } = req.body || {};
  const project = await db.mutate((data) => {
    const p = data.projects[req.params.id];
    if (!p) return null;
    const cut = {
      id: uuidv4(),
      index: p.cuts.length,
      sceneDescription,
      imagePrompt,
      durationSec,
      status: 'pending',
      imagePath: null,
      videoPath: null,
      error: null,
    };
    p.cuts.push(cut);
    p.updatedAt = new Date().toISOString();
    return p;
  });
  if (!project) return res.status(404).json({ error: '프로젝트를 찾을 수 없습니다' });
  res.json(project);
});

// 컷 삭제
app.delete('/api/projects/:id/cuts/:cutId', async (req, res) => {
  const project = await db.mutate((data) => {
    const p = data.projects[req.params.id];
    if (!p) return null;
    p.cuts = p.cuts.filter((c) => c.id !== req.params.cutId);
    p.cuts.forEach((c, i) => (c.index = i));
    p.updatedAt = new Date().toISOString();
    return p;
  });
  if (!project) return res.status(404).json({ error: '프로젝트를 찾을 수 없습니다' });
  res.json(project);
});

// 3) 스토리보드 확정
app.post('/api/projects/:id/confirm', async (req, res) => {
  const project = await db.mutate((data) => {
    const p = data.projects[req.params.id];
    if (!p) return null;
    if (!p.cuts.length) throw new Error('스토리보드에 컷이 없습니다');
    p.status = 'storyboard_confirmed';
    p.updatedAt = new Date().toISOString();
    return p;
  }).catch((err) => {
    res.status(400).json({ error: err.message });
    return undefined;
  });
  if (project === undefined) return;
  if (!project) return res.status(404).json({ error: '프로젝트를 찾을 수 없습니다' });
  res.json(project);
});

// 확정 취소 (다시 편집 가능하게)
app.post('/api/projects/:id/unlock', async (req, res) => {
  const project = await db.mutate((data) => {
    const p = data.projects[req.params.id];
    if (!p) return null;
    p.status = 'storyboard_ready';
    p.updatedAt = new Date().toISOString();
    return p;
  });
  if (!project) return res.status(404).json({ error: '프로젝트를 찾을 수 없습니다' });
  res.json(project);
});

// 4) 확정된 스토리보드로 컷별 이미지+영상 생성 시작 (비동기, 즉시 응답)
app.post('/api/projects/:id/generate', async (req, res) => {
  const project = db.getProject(req.params.id);
  if (!project) return res.status(404).json({ error: '프로젝트를 찾을 수 없습니다' });
  if (project.status !== 'storyboard_confirmed' && project.status !== 'completed') {
    return res.status(400).json({ error: '먼저 스토리보드를 확정하세요' });
  }

  await db.mutate((data) => {
    const p = data.projects[req.params.id];
    p.status = 'generating';
    p.cuts.forEach((c) => {
      if (c.status !== 'video_done') {
        c.status = 'pending';
        c.error = null;
      }
    });
  });

  enqueueProjectGeneration(req.params.id).catch((err) => {
    console.error('생성 큐 오류:', err);
  });

  res.json({ started: true });
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`서버 실행 중: http://localhost:${PORT}`);
  if (!process.env.GOOGLE_API_KEY) {
    console.log('GOOGLE_API_KEY가 없어 MOCK 모드로 동작합니다. (.env 파일에 키를 설정하세요)');
  }
});
