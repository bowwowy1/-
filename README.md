# 숏폼 대본 · 스토리보드 · 영상 생성기

주제를 입력하면 아래 순서로 진행되는 도구입니다.

1. **대본 생성** — 주제를 넣으면 Gemini API로 숏폼(9:16) 대본을 생성
2. **스토리보드 생성** — 대본을 3~6개 컷으로 나눠 각 컷의 장면 설명 + 이미지 프롬프트를 생성 (웹 화면에서 자유롭게 수정/추가/삭제 가능)
3. **스토리보드 확정** — 확정하면 더 이상 컷 내용을 수정할 수 없고(잠금 해제로 되돌릴 수 있음), 생성 단계로 넘어감
4. **컷별 이미지 → 영상 생성** — 확정된 컷마다 Imagen으로 이미지를 생성하고, 그 이미지를 Veo에 넣어 8초짜리 애니메이션 mp4를 생성

**이 도구가 하지 않는 것**: TTS 음성 합성, 자막, BGM, 컷 편집/합치기. 생성된 컷별 mp4를 다운로드해서 CapCut 등에서 직접 편집하는 것을 전제로 합니다.

## 설치

```bash
npm install
cp .env.example .env
# .env 파일에 GOOGLE_API_KEY 입력 (https://aistudio.google.com 에서 발급)
npm start
```

브라우저에서 http://localhost:3000 접속.

`GOOGLE_API_KEY`가 없으면 자동으로 **MOCK 모드**로 동작합니다. 실제 API를 호출하지 않고 더미 텍스트/이미지/영상으로 전체 플로우(대본 → 스토리보드 → 확정 → 생성)를 화면에서 그대로 확인할 수 있습니다. 키를 넣어도 강제로 mock만 쓰고 싶으면 `.env`에 `MOCK_MODE=true`로 설정하세요.

## 모델 설정

`.env`에서 아래 값으로 사용할 모델을 바꿀 수 있습니다.

```
GEMINI_TEXT_MODEL=gemini-2.5-flash
GEMINI_IMAGE_MODEL=imagen-4.0-generate-001
GEMINI_VIDEO_MODEL=veo-3.0-generate-001
```

⚠️ Google이 모델명/REST 응답 스펙을 바꾸는 경우가 있습니다. 특히 `server/providers/veo.js`(영상 생성, long-running operation 폴링 방식)는 정확한 최신 요청/응답 필드를 개발 시점에 검증하지 못했으므로, 실제 키로 처음 호출했을 때 에러가 나면 에러 메시지를 참고해서 해당 파일의 필드명을 [Google AI 개발자 문서](https://ai.google.dev) (Gemini API의 이미지/영상 생성 섹션)에 맞게 조정해야 할 수 있습니다. `server/providers/imagen.js`, `server/providers/geminiText.js`는 비교적 안정적인 REST 패턴을 사용합니다.

## 구조

```
server/
  index.js            Express 서버 + API 라우트
  db.js               파일 기반(JSON) 저장소 (data/db.json)
  queue.js            컷별 이미지→영상 생성 순차 처리 큐
  prompts.js          대본/스토리보드 생성용 프롬프트
  providers/
    geminiText.js      대본/스토리보드용 Gemini 텍스트 생성
    imagen.js           컷 이미지 생성
    veo.js              이미지→영상(8초 애니메이션) 생성
public/               프론트엔드 (바닐라 HTML/CSS/JS)
storage/{projectId}/  생성된 이미지/영상 파일 (다운로드 대상)
data/db.json          프로젝트/스토리보드 상태 저장 (git에는 포함 안 됨)
```

## API 요약

| Method | Path | 설명 |
|---|---|---|
| POST | /api/projects | 주제로 프로젝트 생성 + 대본 생성 |
| GET | /api/projects/:id | 프로젝트 상세 (컷 상태 폴링용) |
| PUT | /api/projects/:id/script | 대본 수동 수정 |
| POST | /api/projects/:id/script/regenerate | 대본 재생성 |
| POST | /api/projects/:id/storyboard | 대본 기반 스토리보드(컷) 생성 |
| PUT | /api/projects/:id/cuts/:cutId | 컷 수정 (확정 전에만) |
| POST | /api/projects/:id/cuts | 컷 추가 |
| DELETE | /api/projects/:id/cuts/:cutId | 컷 삭제 |
| POST | /api/projects/:id/confirm | 스토리보드 확정 |
| POST | /api/projects/:id/unlock | 확정 해제 (재수정) |
| POST | /api/projects/:id/generate | 컷별 이미지+영상 생성 시작 (비동기) |
