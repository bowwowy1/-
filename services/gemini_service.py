import json
import re
import logging

import google.generativeai as genai

import config
from services.errors import PipelineError

logger = logging.getLogger(__name__)

# 5단계 서사 구조 + Micro-Pacing 컷 + T2I/I2V 프롬프트를 한 번에 JSON으로 받기 위한 시스템 프롬프트
SYSTEM_PROMPT = """너는 '비정한 다큐멘터리 숏츠' 전문 작가 겸 프롬프트 엔지니어다.
아래 규칙을 반드시 지켜서 JSON만 출력하라. 다른 설명, 마크다운, 코드블록 없이 순수 JSON 객체 하나만 출력한다.

[대본 규칙]
- 주제를 바탕으로 한국어 다큐 대본을 700~900자 분량으로 작성한다.
- 서사 구조는 반드시 아래 5단계 순서를 따른다.
  1. 도입(충격): 시청자의 주의를 강탈하는 충격적 사실/통계로 시작
  2. 오해(미신): 사람들이 흔히 믿는 잘못된 통념을 제시
  3. 전환구: "그러나 진실은 다르다" 류의 반전 연결어
  4. 해부(생존설계): 냉정하고 건조한 어조로 실제 메커니즘/생존 전략을 해부
  5. 닫는 말: 여운을 남기는 단정적 마무리 문장
- 어조는 감정에 호소하지 않는 '비정한(cold, clinical) 다큐멘터리' 톤을 유지한다.

[컷 분할 규칙]
- 전체 대본을 호흡 단위로 쪼개어 1.5~2.5초 길이의 Micro-Pacing 컷으로 나눈다.
- 각 컷마다 cut_no(1부터), section(위 5단계 중 하나), narration(해당 컷의 한국어 대사),
  duration_sec(1.5~2.5 사이 실수), image_prompt(영문), motion_prompt(영문)를 만든다.
- image_prompt와 motion_prompt는 모두 공통 스타일 문구
  "Zack D Films 3D aesthetic, smooth CGI textures, soft cinematic lighting, 9:16 vertical"
  를 반드시 포함해야 한다.
- image_prompt는 정적 장면 묘사, motion_prompt는 카메라/피사체의 움직임을 묘사한다.

[키워드 규칙]
- 전체 대본에서 시청자에게 강조되어야 할 핵심 단어/숫자를 8~15개 뽑아 keywords 배열로 반환한다.
  (자막에서 노란색으로 강조할 단어들)

[출력 JSON 스키마]
{
  "title": "짧은 후킹 제목",
  "full_script": "700~900자 한국어 전체 대본",
  "keywords": ["단어1", "단어2", "..."],
  "cuts": [
    {
      "cut_no": 1,
      "section": "도입(충격)",
      "narration": "...",
      "duration_sec": 2.0,
      "image_prompt": "...",
      "motion_prompt": "..."
    }
  ]
}
"""


def _extract_json(text: str) -> dict:
    """모델이 코드블록 등을 섞어 반환해도 JSON 객체만 안전하게 추출한다."""
    text = text.strip()
    text = re.sub(r"^```(json)?", "", text.strip(), flags=re.IGNORECASE).strip()
    text = re.sub(r"```$", "", text.strip()).strip()
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise ValueError("응답에서 JSON 객체를 찾을 수 없습니다.")
    return json.loads(match.group(0))


def generate_script_and_prompts(topic: str) -> dict:
    """주제를 받아 대본 + 컷별 T2I/I2V 프롬프트 JSON을 생성한다."""
    if not config.GEMINI_API_KEY:
        raise PipelineError("기획(Gemini)", "GEMINI_API_KEY가 설정되지 않았습니다.")

    try:
        genai.configure(api_key=config.GEMINI_API_KEY)
        model = genai.GenerativeModel(
            model_name=config.GEMINI_MODEL,
            system_instruction=SYSTEM_PROMPT,
            generation_config={
                "response_mime_type": "application/json",
                "temperature": 0.9,
            },
        )
        response = model.generate_content(f"주제: {topic}")
        raw_text = response.text
    except Exception as e:
        logger.exception("Gemini 호출 실패")
        raise PipelineError("기획(Gemini)", f"Gemini API 호출 실패: {e}") from e

    try:
        data = _extract_json(raw_text)
    except Exception as e:
        logger.exception("Gemini 응답 JSON 파싱 실패: %s", raw_text)
        raise PipelineError("기획(Gemini)", f"JSON 파싱 실패: {e}") from e

    _validate_script(data)
    return data


def _validate_script(data: dict):
    required = ["title", "full_script", "keywords", "cuts"]
    for key in required:
        if key not in data:
            raise PipelineError("기획(Gemini)", f"응답 JSON에 '{key}' 필드가 없습니다.")
    if not isinstance(data["cuts"], list) or len(data["cuts"]) == 0:
        raise PipelineError("기획(Gemini)", "cuts 배열이 비어있습니다.")
    for cut in data["cuts"]:
        for key in ("cut_no", "narration", "duration_sec", "image_prompt", "motion_prompt"):
            if key not in cut:
                raise PipelineError("기획(Gemini)", f"cut 객체에 '{key}' 필드가 없습니다.")
