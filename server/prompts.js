function scriptPrompt(topic) {
  return `당신은 유튜브 쇼츠/릴스 전문 작가입니다.
아래 주제로 30~50초 분량의 세로형(9:16) 숏폼 영상 대본을 작성하세요.

주제: "${topic}"

요구사항:
- 시청자의 시선을 3초 안에 사로잡는 훅으로 시작
- 짧고 임팩트 있는 문장 위주
- 내레이션 대사만 작성 (지시문/카메라 용어 없이)
- 마지막은 여운이나 호기심을 남기는 문장으로 마무리
- 한국어로 작성

대본만 출력하세요.`;
}

function storyboardPrompt(topic, script) {
  return `당신은 숏폼 영상 스토리보드 아티스트입니다.
아래 대본을 3~6개의 촬영 컷(장면)으로 나누어 스토리보드를 JSON으로 만드세요.

주제: "${topic}"
대본:
"""
${script}
"""

각 컷은 다음 필드를 가진 객체입니다:
- scene_description: 이 컷에서 어떤 장면이 나오는지 한국어로 1~2문장 설명
- image_prompt: 이 장면의 이미지를 생성하기 위한 영어 프롬프트 (cinematic, 9:16 vertical, 구체적인 묘사 포함)
- duration_sec: 이 컷의 길이(초), 보통 8

다음 JSON 형식으로만 출력하세요 (다른 텍스트 없이):
{"cuts": [{"scene_description": "...", "image_prompt": "...", "duration_sec": 8}, ...]}`;
}

module.exports = { scriptPrompt, storyboardPrompt };
