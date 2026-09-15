const MOCK_MODE = process.env.MOCK_MODE === 'true' || !process.env.GOOGLE_API_KEY;
const MODEL = process.env.GEMINI_TEXT_MODEL || 'gemini-2.5-flash';
const API_KEY = process.env.GOOGLE_API_KEY;

async function callGemini(prompt, { json = false } = {}) {
  if (MOCK_MODE) return mockResponse(prompt, json);

  const url = `https://generativelanguage.googleapis.com/v1beta/models/${MODEL}:generateContent?key=${API_KEY}`;
  const body = {
    contents: [{ parts: [{ text: prompt }] }],
  };
  if (json) {
    body.generationConfig = { responseMimeType: 'application/json' };
  }

  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`Gemini API 오류 (${res.status}): ${errText}`);
  }

  const data = await res.json();
  const text = data?.candidates?.[0]?.content?.parts?.map((p) => p.text).join('') || '';
  if (!text) throw new Error('Gemini 응답에서 텍스트를 찾을 수 없습니다: ' + JSON.stringify(data));
  return text;
}

function mockResponse(prompt, json) {
  if (json) {
    return JSON.stringify({
      cuts: [
        {
          scene_description: '[MOCK] 첫 번째 장면: 도입부 - 주제를 강렬하게 소개',
          image_prompt: 'a dramatic cinematic wide shot introducing the topic, 9:16 vertical, high detail',
          duration_sec: 8,
        },
        {
          scene_description: '[MOCK] 두 번째 장면: 핵심 내용 전개',
          image_prompt: 'a close-up cinematic shot showing the core detail of the topic, 9:16 vertical',
          duration_sec: 8,
        },
        {
          scene_description: '[MOCK] 세 번째 장면: 마무리 및 여운',
          image_prompt: 'a wide atmospheric closing shot, sunset lighting, 9:16 vertical, cinematic',
          duration_sec: 8,
        },
      ],
    });
  }
  return (
    '[MOCK 대본]\n' +
    '(GOOGLE_API_KEY가 설정되지 않아 목업 응답입니다. .env에 키를 넣으면 실제 Gemini 응답으로 대체됩니다.)\n\n' +
    `요청 프롬프트 요약: ${prompt.slice(0, 120)}...`
  );
}

module.exports = { callGemini, MOCK_MODE };
