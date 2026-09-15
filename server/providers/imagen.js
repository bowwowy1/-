const fs = require('fs');

const MOCK_MODE = process.env.MOCK_MODE === 'true' || !process.env.GOOGLE_API_KEY;
const MODEL = process.env.GEMINI_IMAGE_MODEL || 'imagen-4.0-generate-001';
const API_KEY = process.env.GOOGLE_API_KEY;

// 1x1 투명 PNG (mock 모드 placeholder)
const PLACEHOLDER_PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=',
  'base64'
);

/**
 * 이미지 프롬프트로 스토리보드 컷 이미지를 생성해서 파일로 저장한다.
 * @returns {Promise<{mimeType: string, buffer: Buffer}>}
 */
async function generateImage(prompt) {
  if (MOCK_MODE) {
    return { mimeType: 'image/png', buffer: PLACEHOLDER_PNG };
  }

  // NOTE: Imagen REST 스펙은 Google 쪽에서 변경될 수 있습니다.
  // 최신 요청/응답 필드는 https://ai.google.dev (Gemini API - Image generation 문서)에서 확인하세요.
  const url = `https://generativelanguage.googleapis.com/v1beta/models/${MODEL}:predict?key=${API_KEY}`;
  const body = {
    instances: [{ prompt }],
    parameters: { sampleCount: 1, aspectRatio: '9:16' },
  };

  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`Imagen API 오류 (${res.status}): ${errText}`);
  }

  const data = await res.json();
  const prediction = data?.predictions?.[0];
  if (!prediction?.bytesBase64Encoded) {
    throw new Error('Imagen 응답에서 이미지를 찾을 수 없습니다: ' + JSON.stringify(data).slice(0, 500));
  }

  return {
    mimeType: prediction.mimeType || 'image/png',
    buffer: Buffer.from(prediction.bytesBase64Encoded, 'base64'),
  };
}

function saveImage(buffer, filePath) {
  fs.writeFileSync(filePath, buffer);
}

module.exports = { generateImage, saveImage, MOCK_MODE };
