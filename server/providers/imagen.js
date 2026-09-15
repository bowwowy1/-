const fs = require('fs');

const MOCK_MODE = process.env.MOCK_MODE === 'true' || !process.env.GOOGLE_API_KEY;
const MODEL = process.env.GEMINI_IMAGE_MODEL || 'gemini-2.5-flash-image';
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

  // 이 계정은 Imagen(predict) API가 아니라 Gemini 네이티브 이미지 생성
  // 모델(generateContent 방식)에 접근 권한이 있어 이 방식을 사용한다.
  // 사용 가능한 모델 목록은 GET /v1beta/models?key=... 로 확인 가능.
  const url = `https://generativelanguage.googleapis.com/v1beta/models/${MODEL}:generateContent?key=${API_KEY}`;
  const body = {
    contents: [{ parts: [{ text: prompt }] }],
    generationConfig: { imageConfig: { aspectRatio: '9:16' } },
  };

  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`이미지 생성 API 오류 (${res.status}): ${errText}`);
  }

  const data = await res.json();
  const parts = data?.candidates?.[0]?.content?.parts || [];
  const imagePart = parts.find((p) => p.inlineData?.data);
  if (!imagePart) {
    throw new Error('이미지 생성 응답에서 이미지를 찾을 수 없습니다: ' + JSON.stringify(data).slice(0, 500));
  }

  return {
    mimeType: imagePart.inlineData.mimeType || 'image/png',
    buffer: Buffer.from(imagePart.inlineData.data, 'base64'),
  };
}

function saveImage(buffer, filePath) {
  fs.writeFileSync(filePath, buffer);
}

module.exports = { generateImage, saveImage, MOCK_MODE };
