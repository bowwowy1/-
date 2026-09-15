const fs = require('fs');

const MOCK_MODE = process.env.MOCK_MODE === 'true' || !process.env.GOOGLE_API_KEY;
const MODEL = process.env.GEMINI_VIDEO_MODEL || 'veo-3.0-generate-001';
const API_KEY = process.env.GOOGLE_API_KEY;
const POLL_INTERVAL_MS = 10000;
const POLL_TIMEOUT_MS = 10 * 60 * 1000; // 10분

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * 이미지 1장 + 프롬프트로 짧은 애니메이션 영상을 생성한다 (image-to-video).
 * @param {Buffer} imageBuffer
 * @param {string} imageMimeType
 * @param {string} prompt
 * @returns {Promise<Buffer>} mp4 바이너리
 */
async function generateVideoFromImage(imageBuffer, imageMimeType, prompt) {
  if (MOCK_MODE) {
    // 실제 영상 대신 아주 작은 더미 mp4 바이트를 반환 (mock 모드 확인용)
    return Buffer.from('MOCK_VIDEO_PLACEHOLDER_' + Date.now());
  }

  // NOTE: Veo(long-running video generation) REST 스펙은 Google 쪽에서
  // 자주 바뀌는 영역입니다. 아래는 공개된 predictLongRunning 패턴을 따른
  // 최선의 구현이며, 실제 호출 시 에러 메시지를 참고해 필드명을 조정하세요.
  // 최신 스펙: https://ai.google.dev (Gemini API - Video generation / Veo 문서)
  const startUrl = `https://generativelanguage.googleapis.com/v1beta/models/${MODEL}:predictLongRunning?key=${API_KEY}`;
  const startBody = {
    instances: [
      {
        prompt,
        image: {
          bytesBase64Encoded: imageBuffer.toString('base64'),
          mimeType: imageMimeType,
        },
      },
    ],
    parameters: { durationSeconds: 8, aspectRatio: '9:16' },
  };

  const startRes = await fetch(startUrl, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(startBody),
  });

  if (!startRes.ok) {
    const errText = await startRes.text();
    throw new Error(`Veo API 시작 오류 (${startRes.status}): ${errText}`);
  }

  const startData = await startRes.json();
  const operationName = startData.name;
  if (!operationName) {
    throw new Error('Veo 응답에서 operation 이름을 찾을 수 없습니다: ' + JSON.stringify(startData).slice(0, 500));
  }

  const deadline = Date.now() + POLL_TIMEOUT_MS;
  let operation = startData;
  while (!operation.done) {
    if (Date.now() > deadline) throw new Error('Veo 영상 생성 대기 시간 초과');
    await sleep(POLL_INTERVAL_MS);

    const pollUrl = `https://generativelanguage.googleapis.com/v1beta/${operationName}?key=${API_KEY}`;
    const pollRes = await fetch(pollUrl);
    if (!pollRes.ok) {
      const errText = await pollRes.text();
      throw new Error(`Veo API 폴링 오류 (${pollRes.status}): ${errText}`);
    }
    operation = await pollRes.json();
  }

  if (operation.error) {
    throw new Error('Veo 영상 생성 실패: ' + JSON.stringify(operation.error));
  }

  const videoInfo =
    operation.response?.generateVideoResponse?.generatedSamples?.[0]?.video ||
    operation.response?.generatedVideos?.[0]?.video;

  if (!videoInfo) {
    throw new Error('Veo 응답에서 영상 정보를 찾을 수 없습니다: ' + JSON.stringify(operation.response).slice(0, 500));
  }

  if (videoInfo.bytesBase64Encoded) {
    return Buffer.from(videoInfo.bytesBase64Encoded, 'base64');
  }

  if (videoInfo.uri) {
    const fileUrl = videoInfo.uri.includes('?') ? `${videoInfo.uri}&key=${API_KEY}` : `${videoInfo.uri}?key=${API_KEY}`;
    const fileRes = await fetch(fileUrl);
    if (!fileRes.ok) throw new Error(`Veo 영상 다운로드 오류 (${fileRes.status})`);
    return Buffer.from(await fileRes.arrayBuffer());
  }

  throw new Error('Veo 응답에 영상 바이트/URI가 없습니다: ' + JSON.stringify(videoInfo).slice(0, 500));
}

function saveVideo(buffer, filePath) {
  fs.writeFileSync(filePath, buffer);
}

module.exports = { generateVideoFromImage, saveVideo, MOCK_MODE };
