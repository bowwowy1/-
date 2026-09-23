import html as html_lib
import json
import re
from datetime import date, datetime
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

PROMPT_PATH = Path(__file__).parent / "prompts" / "travel.txt"
ANGLES_PROMPT_PATH = Path(__file__).parent / "prompts" / "angles.txt"
OUTPUTS_DIR = Path(__file__).parent / "outputs"
MODEL_ID = "claude-sonnet-5"


def load_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def load_angles_prompt() -> str:
    return ANGLES_PROMPT_PATH.read_text(encoding="utf-8")


def build_user_message(
    country: str,
    trip_type: str,
    references: str,
    notes: str,
    focus_angle: str = "",
) -> str:
    focus = focus_angle.strip() if focus_angle else ""
    if focus:
        focus_line = (
            f"이번 편 집중 각도: {focus}\n"
            "→ 5개 섹션 구조는 유지하되 이 각도 하나만 깊게 다뤄라. "
            "다른 주제는 한 문장 이상 언급하지 마라. 역사적 배경과 현재 "
            "규정을 구체적으로 써라. 제목 후보에도 이 각도 키워드를 넣어라.\n"
        )
    else:
        focus_line = "이번 편 집중 각도: (없음. 종합편으로 쓰기)\n"

    return (
        f"나라: {country}\n"
        f"여행 유형: {trip_type}\n"
        f"{focus_line}\n"
        f"[참고자료 — 외교부 해외안전여행·대사관 공지 원문]\n{references or '(없음)'}\n\n"
        f"[내가 아는 사실/관점 메모]\n{notes or '(없음)'}\n\n"
        "아래 JSON 형식으로만 응답하라. 코드펜스나 다른 설명 없이 JSON 하나만 출력한다.\n"
        "{\n"
        '  "titles": ["제목 후보 10개, 문자열 배열"],\n'
        '  "body_html": "HTML 태그로 작성된 본문. <p>, <h3>, <ul>, <li> 등을 사용. 마크다운 금지. 썸네일 아이디어를 여기에 쓰지 말 것.",\n'
        '  "tags": ["태그 15개, 문자열 배열. # 없이 단어만"],\n'
        '  "thumbnails": ["썸네일 아이디어 2개, 각각 한 문장 (구도 + 텍스트 + 색감)"]\n'
        "}"
    )


def strip_code_fence(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        first_newline = t.find("\n")
        if first_newline != -1:
            t = t[first_newline + 1 :]
        if t.endswith("```"):
            t = t[: -3]
    return t.strip()


class ResponseParseError(Exception):
    def __init__(self, message: str, raw_text: str, stop_reason: str | None = None):
        super().__init__(message)
        self.raw_text = raw_text
        self.stop_reason = stop_reason


def _js_literal(value) -> str:
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")


def html_for_clipboard(html: str) -> str:
    def replace_heading(match: re.Match) -> str:
        inner = match.group(2)
        return f'<p><strong><span style="font-size:19px">{inner}</span></strong></p>'

    return re.sub(
        r"<(h[23])(?:\s[^>]*)?>(.*?)</\1>",
        replace_heading,
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )


def render_copy_button(label: str, plain_text: str, html_text: str | None, key: str) -> None:
    plain_js = _js_literal(plain_text)
    html_js = _js_literal(html_text) if html_text is not None else "null"
    btn_id = f"cpbtn_{key}"
    status_id = f"cpstatus_{key}"
    component_html = f"""
    <div style="display:flex;align-items:center;gap:10px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
      <button id="{btn_id}" style="padding:6px 14px;border:1px solid #d0d0d0;border-radius:6px;background:#f7f7f7;cursor:pointer;font-size:13px;">
        {label}
      </button>
      <span id="{status_id}" style="font-size:13px;color:#2b8a3e;"></span>
    </div>
    <script>
      (function() {{
        const btn = document.getElementById("{btn_id}");
        const status = document.getElementById("{status_id}");
        const plain = {plain_js};
        const html = {html_js};
        btn.addEventListener("click", async () => {{
          try {{
            if (html !== null && window.ClipboardItem && navigator.clipboard && navigator.clipboard.write) {{
              const tmp = document.createElement("div");
              tmp.innerHTML = html;
              const plainFromHtml = tmp.innerText;
              const item = new ClipboardItem({{
                "text/html": new Blob([html], {{type: "text/html"}}),
                "text/plain": new Blob([plainFromHtml], {{type: "text/plain"}}),
              }});
              await navigator.clipboard.write([item]);
            }} else {{
              await navigator.clipboard.writeText(plain);
            }}
            status.style.color = "#2b8a3e";
            status.textContent = "복사됨";
            setTimeout(() => {{ status.textContent = ""; }}, 2000);
          }} catch (e) {{
            status.style.color = "#c92a2a";
            status.textContent = "복사 실패: " + e.message;
          }}
        }});
      }})();
    </script>
    """
    components.html(component_html, height=44)


GENERATE_TOOL = {
    "name": "submit_travel_draft",
    "description": "생성한 여행 블로그 초안 (제목 후보 10개, HTML 본문, 태그 15개, 썸네일 아이디어 2개)을 제출한다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "titles": {
                "type": "array",
                "items": {"type": "string"},
                "description": "제목 후보 문자열 10개",
                "minItems": 10,
                "maxItems": 10,
            },
            "body_html": {
                "type": "string",
                "description": "HTML 태그(<p>, <h3>, <ul>, <li> 등)로 작성된 본문. 마크다운 금지. 썸네일 아이디어는 절대 본문에 쓰지 말 것.",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "태그 문자열 15개 (# 없이 단어만).",
                "minItems": 15,
                "maxItems": 15,
            },
            "thumbnails": {
                "type": "array",
                "items": {"type": "string"},
                "description": "썸네일 아이디어 2개. 각각 한 문장으로 구도·텍스트·색감을 담는다. 본문과 분리.",
                "minItems": 2,
                "maxItems": 2,
            },
        },
        "required": ["titles", "body_html", "tags", "thumbnails"],
    },
}

CLAIMS_TOOL = {
    "name": "submit_legal_claims",
    "description": "본문에서 추출한 법률·처벌 관련 사실 주장 문장 배열을 제출한다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "claims": {
                "type": "array",
                "items": {"type": "string"},
                "description": "검증 대상 주장 문장 (HTML 태그 제거, 한 문장씩)",
            },
        },
        "required": ["claims"],
    },
}

VERIFY_TOOL = {
    "name": "submit_verdict",
    "description": "web_search 로 확인한 결과를 바탕으로 주장에 대한 최종 판정을 제출한다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {
                "type": "string",
                "enum": ["근거있음", "근거미발견", "상충"],
                "description": "정부·대사관·공신력 있는 기관 문서 확인 결과",
            },
            "sources": {
                "type": "array",
                "items": {"type": "string"},
                "description": "실제로 확인한 출처 URL 배열. 없으면 빈 배열.",
            },
            "summary": {
                "type": "string",
                "description": "1~2문장 근거 요약. 확인 실패 시 그 사유.",
            },
        },
        "required": ["verdict", "sources", "summary"],
    },
}

COLLECT_REFERENCES_TOOL = {
    "name": "submit_reference_paragraphs",
    "description": "web_search 로 찾은 법률·처벌·반입 규제 관련 문단과 출처 URL을 제출한다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "paragraphs": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "법률·처벌·반입 규제 관련 문단. 원문을 최대한 그대로 보존.",
                        },
                        "url": {
                            "type": "string",
                            "description": "이 문단이 나온 실제 출처 URL",
                        },
                    },
                    "required": ["content", "url"],
                },
                "description": "발췌한 문단 목록. 관련 자료가 없으면 빈 배열.",
            },
        },
        "required": ["paragraphs"],
    },
}

ANGLES_TOOL = {
    "name": "submit_angle_candidates",
    "description": "여행 블로그 편별 각도 후보 8개를 제출한다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "candidates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "각도 제목 (한 줄, 짧게)",
                        },
                        "explanation": {
                            "type": "string",
                            "description": "이 각도로 한 편이 되는 이유 (한 줄)",
                        },
                    },
                    "required": ["title", "explanation"],
                },
                "minItems": 8,
                "maxItems": 8,
                "description": "각도 후보 8개",
            },
        },
        "required": ["candidates"],
    },
}


def _extract_tool_input(resp, *, tool_name: str) -> dict:
    """응답에서 특정 이름의 client-side tool_use 블록을 찾아 input(dict)을 돌려준다.
    실패 시 ResponseParseError 에 원문 전체를 실어 던진다."""
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == tool_name:
            return dict(block.input)

    lines: list[str] = []
    for block in resp.content:
        btype = getattr(block, "type", "unknown")
        if btype == "text":
            lines.append(f"[text] {block.text}")
        elif btype == "tool_use":
            lines.append(f"[tool_use name={getattr(block, 'name', '?')}] {json.dumps(getattr(block, 'input', {}), ensure_ascii=False)}")
        elif btype == "server_tool_use":
            lines.append(f"[server_tool_use name={getattr(block, 'name', '?')}] {json.dumps(getattr(block, 'input', {}), ensure_ascii=False)}")
        elif btype == "web_search_tool_result":
            lines.append(f"[web_search_tool_result] {getattr(block, 'content', '')}")
        else:
            lines.append(f"[{btype}] {block!r}")
    raw_text = "\n".join(lines) or "(빈 응답)"
    stop_reason = getattr(resp, "stop_reason", None)
    raise ResponseParseError(
        f"tool_use 블록({tool_name})을 찾지 못했습니다.",
        raw_text,
        stop_reason,
    )


def generate(
    country: str,
    trip_type: str,
    references: str,
    notes: str,
    focus_angle: str = "",
) -> dict:
    client = Anthropic()
    resp = client.messages.create(
        model=MODEL_ID,
        max_tokens=16000,
        system=load_system_prompt(),
        messages=[{
            "role": "user",
            "content": build_user_message(country, trip_type, references, notes, focus_angle),
        }],
        tools=[GENERATE_TOOL],
        tool_choice={"type": "tool", "name": GENERATE_TOOL["name"]},
    )
    return _extract_tool_input(resp, tool_name=GENERATE_TOOL["name"])


def extract_legal_claims(body_html: str) -> list[str]:
    client = Anthropic()
    resp = client.messages.create(
        model=MODEL_ID,
        max_tokens=8000,
        system=(
            "너는 여행 블로그 본문에서 '단정된 구체적 법률 주장' 문장만 "
            "추출하는 도구다. 불확실성이 이미 표시된 문장, 자료를 가리키는 "
            "메타 문장, 주어가 없어 무엇을 검증할지 모호한 문장, 그리고 "
            "문화·예절·종교 관습·사기 수법·안전 조언은 절대 추출하지 마라. "
            "반드시 submit_legal_claims 도구를 호출해 결과를 제출하라."
        ),
        messages=[{
            "role": "user",
            "content": (
                "아래 HTML 본문에서 다음 두 형태 중 하나에 해당하는 문장만 "
                "추출하라. 그 외에는 모두 제외.\n"
                "\n"
                "포함 대상 (구체적·단정된 법률 주장):\n"
                "A) '특정 행위가 처벌 대상이다' 형태\n"
                "   (무엇을 하면 → 어떤 처벌을 받는다)\n"
                "B) '형량·벌금 액수가 얼마다' 형태\n"
                "   (구체적인 기간·금액이 명시된 처벌)\n"
                "\n"
                "반드시 제외 (검증 표에 나타나면 안 됨):\n"
                "- '확인 필요', '확인이 필요하지만', '확인해봐야 하지만',\n"
                "  '알려져 있지만 근거는 불명확', '알려진 바에 따르면' 등\n"
                "  이미 불확실성을 표시한 문장. (검증 대상은 단정된 주장뿐.)\n"
                "- '공지 원문에 나와 있다', '외교부 자료에 언급된다',\n"
                "  '자료에 따르면' 같이 자료 자체를 가리키는 메타 문장.\n"
                "  (자료를 인용한 사실 서술은 그 인용된 규정 자체가 A/B 형태\n"
                "   여야만 추출.)\n"
                "- 주어가 특정되지 않아 '무엇이 처벌되는지' 알 수 없는 문장.\n"
                "  (예: '위반하면 처벌될 수 있다' — 어떤 위반인지 불명확)\n"
                "- 문화적·종교적 관습, 예절, 결례, 몸짓 (법적 강제력 없음).\n"
                "- 사기 수법, 안전 조언, 주의사항, 일반 팁.\n"
                "- '주의가 필요하다', '조심하라' 같은 경고성 문장.\n"
                "- 역사·제도 배경 서술 (법 조항이 아닌 설명).\n"
                "\n"
                "규칙:\n"
                "- HTML 태그는 제거하고 자연스러운 한 문장으로 정리한다.\n"
                "- 한 문단에 여러 법률 주장이 있으면 각각 별도 항목으로 쪼갠다.\n"
                "- 문장 그 자체로 검증 가능해야 한다 (지시어 대체, 주어 명시).\n"
                "- 요약하거나 다시 쓰지 말고, 원문의 사실 진술을 최대한 그대로 보존한다.\n"
                "- 추출한 문장 안에 '확인 필요' 같은 불확실성 표시가 남아 있으면\n"
                "  그 문장은 제외한다.\n"
                "- 조건을 만족하는 문장이 하나도 없으면 빈 배열을 반환하라.\n\n"
                f"본문:\n{body_html}"
            ),
        }],
        tools=[CLAIMS_TOOL],
        tool_choice={"type": "tool", "name": CLAIMS_TOOL["name"]},
    )
    data = _extract_tool_input(resp, tool_name=CLAIMS_TOOL["name"])
    return [c for c in data.get("claims", []) if isinstance(c, str) and c.strip()]


def _collect_search_urls(resp) -> list[str]:
    """응답 안의 web_search_tool_result 블록에서 URL 목록을 뽑는다."""
    urls: list[str] = []
    for block in resp.content:
        if getattr(block, "type", None) != "web_search_tool_result":
            continue
        content = getattr(block, "content", None)
        if not isinstance(content, list):
            continue
        for item in content:
            url = None
            if hasattr(item, "url"):
                url = getattr(item, "url", None)
            elif isinstance(item, dict):
                url = item.get("url")
            if isinstance(url, str) and url:
                urls.append(url)
    return urls


def _find_submit_verdict(resp):
    for block in resp.content:
        if (
            getattr(block, "type", None) == "tool_use"
            and getattr(block, "name", None) == VERIFY_TOOL["name"]
        ):
            return block
    return None


def verify_claim(claim: str, country: str) -> dict:
    """web_search + submit_verdict 다중 tool 루프. 최대 2회 반복.
    검색된 URL이 없으면 verdict 를 '근거미발견'으로 강제한다.
    검색·판정 모두 '대상 국가(country)' 의 법률만 근거로 인정한다."""
    client = Anthropic()
    country_name = (country or "").strip() or "(미상)"
    system_prompt = (
        f"너는 '{country_name}' 여행자에게 필요한 법률·처벌 주장을 "
        f"'{country_name}'의 정부·법원·의회·주한 대사관 공지·현지 언론 "
        "자료로만 검증하는 도구다.\n"
        "\n"
        "필수 순서:\n"
        f"1) web_search 로 반드시 '{country_name}' 이름을 포함한 쿼리로 검색한다.\n"
        f"   예: '{country_name} 왕실모독죄 SNS 처벌', '{country_name} 마약 소지 형량',\n"
        f"       '{country_name} 관세법 반입 금지'.\n"
        "2) 검색 결과를 근거로 submit_verdict 도구를 호출해 최종 판정을 제출한다.\n"
        "\n"
        "엄격한 규칙 — 근거 채택 기준:\n"
        f"- 대상 국가('{country_name}')의 법률·정부기관·현지 언론 자료만\n"
        "  근거로 인정한다.\n"
        "- 한국 국내법(예: 대한민국 형법 제311조, 정보통신망법, 대법원 판례 등)이나\n"
        "  다른 나라 법률에 관한 자료는 아무리 관련 있어 보여도 근거로 채택하지\n"
        f"  마라. 그런 자료뿐이면 verdict 는 반드시 '근거미발견' 이다.\n"
        "- 사전 지식만으로는 절대 '근거있음' 판정을 내리지 마라.\n"
        "- web_search 결과에 신뢰할 만한 URL이 없으면 verdict 는 반드시 '근거미발견'.\n"
        "- 검색이 충분하다고 판단되면 반드시 submit_verdict 를 호출해 마무리하라."
    )
    messages: list[dict] = [{
        "role": "user",
        "content": (
            f"대상 국가: {country_name}\n"
            f"아래 주장을 '{country_name}' 의 법률·처벌 관점에서 검증하라.\n"
            f"web_search 쿼리에는 반드시 '{country_name}' 이름을 포함시킨다.\n"
            f"- {country_name} 정부·대사관·공신력 있는 기관 문서에서 확인되면\n"
            "  verdict: 근거있음\n"
            "- 신뢰할 만한 출처를 찾지 못하거나 확인이 안 되면 verdict: 근거미발견\n"
            f"- 검색 결과가 {country_name} 법이 아니라 한국 국내법이나 제3국 법을\n"
            "  다루면 근거로 쓰지 말고 verdict: 근거미발견\n"
            f"- 신뢰할 만한 {country_name} 자료가 주장과 반대되면 verdict: 상충\n"
            "sources 에는 실제로 확인한 URL만 넣어라. 없으면 빈 배열.\n"
            "summary 는 1~2문장으로 근거를 요약하라.\n\n"
            f"주장: {claim}"
        ),
    }]
    tools = [
        {"type": "web_search_20250305", "name": "web_search", "max_uses": 1},
        VERIFY_TOOL,
    ]

    all_search_urls: list[str] = []
    verdict_data: dict | None = None
    last_resp = None

    for _ in range(2):
        resp = client.messages.create(
            model=MODEL_ID,
            max_tokens=8000,
            tools=tools,
            tool_choice={"type": "any"},
            system=system_prompt,
            messages=messages,
        )
        last_resp = resp
        all_search_urls.extend(_collect_search_urls(resp))

        submit_block = _find_submit_verdict(resp)
        if submit_block is not None:
            verdict_data = dict(submit_block.input)
            break

        # submit_verdict 아직 없음 → 응답을 대화에 넣고 재호출
        messages.append({"role": "assistant", "content": resp.content})
        messages.append({
            "role": "user",
            "content": (
                "검색이 충분하다. 이제 submit_verdict 도구를 호출해 최종 판정을 "
                "제출하라. 신뢰할 만한 URL을 찾지 못했다면 verdict 는 '근거미발견' "
                "이어야 한다."
            ),
        })

    if verdict_data is None:
        # 2회 안에 submit_verdict 를 못 받았다. raw 를 실어 에러로 던진다.
        try:
            _extract_tool_input(last_resp, tool_name=VERIFY_TOOL["name"])
        except ResponseParseError:
            raise
        raise ResponseParseError(
            "2회 반복 후에도 submit_verdict 호출이 없었습니다.",
            f"수집된 web_search URL: {all_search_urls}",
            getattr(last_resp, "stop_reason", None),
        )

    verdict = verdict_data.get("verdict", "근거미발견")
    if verdict not in ("근거있음", "근거미발견", "상충"):
        verdict = "근거미발견"
    sources = [s for s in verdict_data.get("sources", []) if isinstance(s, str)]
    summary = verdict_data.get("summary", "") or ""

    # 웹 검색에서 URL을 하나도 수집하지 못했다면 판정 강제 다운그레이드.
    # (모델이 사전 지식만으로 근거있음/상충 판정을 내는 것을 차단)
    if not all_search_urls:
        verdict = "근거미발견"
        prefix = "웹 검색 결과 없음. "
        summary = prefix + summary if summary else prefix.strip()

    return {"verdict": verdict, "sources": sources, "summary": summary}


def collect_references(country: str) -> str:
    """나라 이름으로 web_search 를 실행해 법률·처벌·반입 규제 관련 문단을
    수집하고, 참고자료 입력란에 그대로 붙여넣을 수 있는 텍스트로 돌려준다.
    관련 자료를 찾지 못했으면 빈 문자열."""
    client = Anthropic()
    system_prompt = (
        "너는 여행자가 알아야 할 법률·처벌·반입 규제 정보를 정부·대사관·"
        "공신력 있는 기관 문서에서 수집하는 도구다.\n"
        "\n"
        "필수 순서:\n"
        "1) 반드시 web_search 도구로 실제 출처를 검색한다.\n"
        "2) 검색 결과에서 법률·처벌·반입 규제와 관련된 문단만 추린다.\n"
        "3) submit_reference_paragraphs 도구를 호출해 결과를 제출한다.\n"
        "\n"
        "규칙:\n"
        "- 문단은 원문을 최대한 그대로 보존한다. 요약·재작성 금지.\n"
        "- 각 문단마다 실제로 확인한 출처 URL을 함께 넣는다.\n"
        "- 법률·처벌·반입 규제와 무관한 문단은 넣지 마라.\n"
        "- 관련 자료를 하나도 찾지 못하면 paragraphs 를 빈 배열로 제출한다."
    )
    queries = [
        f'"{country} 외교부 해외안전여행 처벌 법규"',
        f'"{country} 주재 한국대사관 공지 벌금 처벌"',
    ]
    messages: list[dict] = [{
        "role": "user",
        "content": (
            f"'{country}' 여행자에게 필요한 법률·처벌·반입 규제 정보를 "
            "수집하라. 다음 두 검색어를 사용한다:\n"
            f"1) {queries[0]}\n"
            f"2) {queries[1]}\n\n"
            "검색이 끝나면 submit_reference_paragraphs 를 호출하여 각 "
            "문단과 출처 URL을 넘겨라."
        ),
    }]
    tools = [
        {"type": "web_search_20250305", "name": "web_search", "max_uses": 2},
        COLLECT_REFERENCES_TOOL,
    ]

    paragraphs: list[dict] | None = None
    for _ in range(2):
        resp = client.messages.create(
            model=MODEL_ID,
            max_tokens=8000,
            tools=tools,
            tool_choice={"type": "any"},
            system=system_prompt,
            messages=messages,
        )
        submit_block = next(
            (
                b
                for b in resp.content
                if getattr(b, "type", None) == "tool_use"
                and getattr(b, "name", None) == COLLECT_REFERENCES_TOOL["name"]
            ),
            None,
        )
        if submit_block is not None:
            data = dict(submit_block.input)
            raw = data.get("paragraphs", [])
            paragraphs = [p for p in raw if isinstance(p, dict)]
            break
        messages.append({"role": "assistant", "content": resp.content})
        messages.append({
            "role": "user",
            "content": (
                "검색이 충분하다. 이제 submit_reference_paragraphs 도구를 "
                "호출해 결과를 제출하라. 관련 자료가 없으면 paragraphs 를 "
                "빈 배열로 넣어라."
            ),
        })

    if not paragraphs:
        return ""

    blocks: list[str] = []
    for p in paragraphs:
        content = (p.get("content") or "").strip()
        url = (p.get("url") or "").strip()
        if not content:
            continue
        block = content
        if url:
            block += f"\n출처: {url}"
        blocks.append(block)
    return "\n\n".join(blocks)


def extract_angles(country: str, references: str) -> list[dict]:
    """나라 이름과 참고자료로 편별 각도 후보 8개 뽑기. 짧은 호출."""
    client = Anthropic()
    resp = client.messages.create(
        model=MODEL_ID,
        max_tokens=2000,
        system=load_angles_prompt(),
        messages=[{
            "role": "user",
            "content": (
                f"나라: {country}\n\n"
                f"[참고자료 — 외교부 해외안전여행·대사관 공지 등]\n"
                f"{references or '(없음)'}\n\n"
                "위 정보를 바탕으로 이 나라 여행 블로그를 8편으로 나눌 각도 후보 "
                "8개를 만들어 submit_angle_candidates 도구로 제출하라."
            ),
        }],
        tools=[ANGLES_TOOL],
        tool_choice={"type": "tool", "name": ANGLES_TOOL["name"]},
    )
    data = _extract_tool_input(resp, tool_name=ANGLES_TOOL["name"])
    raw = data.get("candidates", [])
    result: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        title = (item.get("title") or "").strip()
        explanation = (item.get("explanation") or "").strip()
        if title:
            result.append({"title": title, "explanation": explanation})
    return result


def render_verification_table(rows: list[dict]) -> None:
    def cell(text: str) -> str:
        return html_lib.escape(text).replace("\n", "<br>")

    parts = [
        '<table style="width:100%;border-collapse:collapse;font-size:14px;">',
        '<thead><tr style="background:#f1f3f5;">',
        '<th style="text-align:left;border:1px solid #dee2e6;padding:8px;width:32%;">주장 문장</th>',
        '<th style="text-align:left;border:1px solid #dee2e6;padding:8px;width:10%;">판정</th>',
        '<th style="text-align:left;border:1px solid #dee2e6;padding:8px;width:22%;">출처 URL</th>',
        '<th style="text-align:left;border:1px solid #dee2e6;padding:8px;width:36%;">검색된 근거 요약</th>',
        "</tr></thead><tbody>",
    ]
    for row in rows:
        verdict = row["verdict"]
        if verdict == "근거미발견":
            row_style = "color:#c92a2a;"
        elif verdict == "미검증":
            row_style = "color:#868e96;"
        else:
            row_style = ""
        urls_html = "<br>".join(
            f'<a href="{html_lib.escape(u, quote=True)}" target="_blank" rel="noopener">{html_lib.escape(u)}</a>'
            for u in row["sources"]
        ) or "<span style=\"color:#868e96;\">(없음)</span>"
        parts.append(f'<tr style="{row_style}">')
        parts.append(f'<td style="border:1px solid #dee2e6;padding:8px;vertical-align:top;">{cell(row["claim"])}</td>')
        parts.append(f'<td style="border:1px solid #dee2e6;padding:8px;vertical-align:top;"><strong>{cell(verdict)}</strong></td>')
        parts.append(f'<td style="border:1px solid #dee2e6;padding:8px;vertical-align:top;word-break:break-all;">{urls_html}</td>')
        parts.append(f'<td style="border:1px solid #dee2e6;padding:8px;vertical-align:top;">{cell(row["summary"])}</td>')
        parts.append("</tr>")
    parts.append("</tbody></table>")
    st.markdown("".join(parts), unsafe_allow_html=True)


def _safe_country_for_filename(country: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\s]+', "_", country).strip("_")
    return cleaned or "unknown"


def save_output(payload: dict) -> Path:
    OUTPUTS_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    fname = f"{_safe_country_for_filename(payload.get('country', ''))}_{ts}.json"
    path = OUTPUTS_DIR / fname
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def list_outputs() -> list[Path]:
    if not OUTPUTS_DIR.exists():
        return []
    return sorted(OUTPUTS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)


def display_label(path: Path) -> str:
    match = re.match(r"(.+)_(\d{8})_(\d{4})$", path.stem)
    if not match:
        return path.stem
    country, ds, ts = match.groups()
    return f"{country} · {ds[:4]}-{ds[4:6]}-{ds[6:]} {ts[:2]}:{ts[2:]}"


def run_verification(body_html: str, country: str) -> list[dict]:
    """법률 주장 추출 + 상위 6건 웹 검색 검증. 진행 상황을 화면에 표시."""
    with st.spinner("본문에서 법률 관련 주장 추출 중..."):
        try:
            claims = extract_legal_claims(body_html)
        except ResponseParseError as e:
            st.error(f"주장 추출 응답을 JSON으로 파싱하지 못했습니다: {e}")
            if e.stop_reason == "max_tokens":
                st.warning("응답이 잘렸습니다 (stop_reason=max_tokens).")
            with st.expander("응답 원문 (원인 확인용)", expanded=True):
                st.code(e.raw_text or "(빈 응답)", language="json")
            return []
        except Exception as e:
            st.error(f"주장 추출 실패: {e}")
            return []

    if not claims:
        return []

    VERIFY_LIMIT = 6
    priority_claims = [c for c in claims if "확인 필요" in c]
    other_claims = [c for c in claims if "확인 필요" not in c]
    ordered = priority_claims + other_claims
    to_verify = ordered[:VERIFY_LIMIT]
    skipped = ordered[VERIFY_LIMIT:]

    if skipped:
        st.caption(
            f"비용 절감을 위해 상위 {VERIFY_LIMIT}건만 웹 검색으로 검증합니다. "
            f"나머지 {len(skipped)}건은 '미검증' 으로 표시됩니다."
        )

    rows: list[dict] = []
    progress = st.progress(0.0, text=f"검증 중 0/{len(to_verify)}")
    for i, claim in enumerate(to_verify):
        try:
            v = verify_claim(claim, country)
        except Exception as e:
            v = {"verdict": "근거미발견", "sources": [], "summary": f"(검증 오류) {e}"}
        rows.append({"claim": claim, **v})
        progress.progress((i + 1) / len(to_verify), text=f"검증 중 {i + 1}/{len(to_verify)}")
    progress.empty()

    for claim in skipped:
        rows.append({
            "claim": claim,
            "verdict": "미검증",
            "sources": [],
            "summary": "비용 절감으로 검증 생략",
        })

    return rows


def render_result(result: dict) -> None:
    country = result.get("country", "")
    trip_type = result.get("trip_type", "")
    generated_at = result.get("generated_at", "")
    titles = result.get("titles", [])
    body_html = result.get("body_html", "")
    tags = result.get("tags", [])
    thumbnails = result.get("thumbnails", [])
    verification_rows = result.get("verification_rows", [])

    if country or trip_type or generated_at:
        parts = [p for p in (country, trip_type, generated_at) if p]
        st.caption(" · ".join(parts))

    titles_text = "\n".join(f"{i}. {t}" for i, t in enumerate(titles, 1))
    tags_text = " ".join(f"#{tag}" for tag in tags)

    st.subheader("제목 후보 10개")
    render_copy_button("제목 복사", titles_text, None, key="titles")
    for i, title in enumerate(titles, 1):
        st.write(f"{i}. {title}")

    st.subheader("본문")
    body_html_for_clipboard = html_for_clipboard(body_html)
    render_copy_button("본문 복사 (서식 유지)", body_html_for_clipboard, body_html_for_clipboard, key="body")
    st.markdown(body_html, unsafe_allow_html=True)

    st.subheader("썸네일 아이디어")
    if not thumbnails:
        st.info("썸네일 아이디어가 없습니다.")
    else:
        for i, thumb in enumerate(thumbnails, 1):
            st.write(f"{i}. {thumb}")

    st.subheader("태그 15개")
    render_copy_button("태그 복사", tags_text, None, key="tags")
    st.write(tags_text)

    st.subheader(f"법률 정보 검증 ({len(verification_rows)}건)")
    st.caption("본문은 자동으로 수정되지 않습니다. 검증 결과는 참고용으로만 표시합니다.")
    if not verification_rows:
        st.info("검증할 법률·처벌 관련 주장이 없거나 검증 결과가 비어 있습니다.")
    else:
        render_verification_table(verification_rows)


st.set_page_config(page_title="여행 블로그 초안 생성기", layout="wide")

# 사이드바: 저장된 초안 목록
with st.sidebar:
    st.header("저장된 초안")
    test_mode = st.checkbox(
        "테스트 모드",
        value=False,
        key="test_mode",
        help="API 호출 없이 outputs/ 최근 파일을 그대로 불러와 UI 확인용.",
    )
    outputs = list_outputs()
    if not outputs:
        st.caption("저장된 초안 없음")
    for path in outputs:
        pending = st.session_state.get("confirm_delete") == path.name
        if pending:
            st.caption(f"'{display_label(path)}' 삭제할까요?")
            c_yes, c_no = st.columns(2)
            with c_yes:
                if st.button(
                    "정말 지우기",
                    key=f"delyes_{path.stem}",
                    type="primary",
                    use_container_width=True,
                ):
                    was_loaded = st.session_state.get("loaded_from") == path.name
                    try:
                        path.unlink()
                    except FileNotFoundError:
                        pass
                    except Exception as e:
                        st.error(f"삭제 실패: {e}")
                    st.session_state.pop("confirm_delete", None)
                    if was_loaded:
                        st.session_state.pop("result", None)
                        st.session_state.pop("loaded_from", None)
                    st.rerun()
            with c_no:
                if st.button("취소", key=f"delno_{path.stem}", use_container_width=True):
                    st.session_state.pop("confirm_delete", None)
                    st.rerun()
        else:
            c_load, c_del = st.columns([5, 1])
            with c_load:
                if st.button(
                    display_label(path),
                    key=f"load_{path.stem}",
                    use_container_width=True,
                ):
                    try:
                        data = json.loads(path.read_text(encoding="utf-8"))
                    except Exception as e:
                        st.error(f"불러오기 실패: {e}")
                    else:
                        st.session_state["result"] = data
                        st.session_state["loaded_from"] = path.name
                        st.rerun()
            with c_del:
                if st.button(
                    "×",
                    key=f"del_{path.stem}",
                    help="삭제",
                    use_container_width=True,
                ):
                    st.session_state["confirm_delete"] = path.name
                    st.rerun()

    if st.session_state.get("result"):
        st.divider()
        if st.button("새 초안 작성", use_container_width=True):
            st.session_state.pop("result", None)
            st.session_state.pop("loaded_from", None)
            st.rerun()

st.title("여행 블로그 초안 생성기")

# st.form 을 쓰면 위젯 변경이 실시간 rerun 을 트리거하지 않아 조건부
# 경고를 낼 수 없다. 그래서 form 없이 평범한 위젯 + st.button 으로 구성.
country = st.text_input("나라 이름", placeholder="예: 튀르키예")
focus_angle = st.text_input(
    "이번 편 집중 각도 (비워두면 종합편)",
    placeholder="예: 왕실모독죄, 사원 예절, 툭툭 사기",
    key="focus_angle_input",
)
trip_type = st.selectbox("여행 유형", ["관광", "출장", "장기체류"])

helper_disabled = not country.strip() or st.session_state.get("test_mode", False)
helper_help = None
if not country.strip():
    helper_help = "나라 이름을 먼저 입력하세요."
elif st.session_state.get("test_mode", False):
    helper_help = "테스트 모드에서는 사용할 수 없습니다."

col_collect, col_angles = st.columns(2)
with col_collect:
    if st.button(
        "참고자료 자동 수집",
        disabled=helper_disabled,
        help=helper_help,
        use_container_width=True,
    ):
        with st.spinner(f"'{country.strip()}' 관련 자료 검색 중..."):
            try:
                collected = collect_references(country.strip())
                err = None
            except Exception as e:
                collected = ""
                err = str(e)
        st.session_state["references_input"] = collected
        if err:
            st.session_state["_collect_error"] = err
        elif not collected:
            st.session_state["_collect_failed"] = True
        st.rerun()
with col_angles:
    if st.button(
        "각도 후보 뽑기",
        disabled=helper_disabled,
        help=helper_help,
        use_container_width=True,
    ):
        with st.spinner(f"'{country.strip()}' 각도 후보 생성 중..."):
            try:
                cands = extract_angles(
                    country.strip(),
                    st.session_state.get("references_input", ""),
                )
                st.session_state["angle_candidates"] = cands
                st.session_state.pop("_angle_error", None)
            except Exception as e:
                st.session_state["angle_candidates"] = []
                st.session_state["_angle_error"] = str(e)
        st.session_state.pop("angle_choice_idx", None)
        st.rerun()

collect_err = st.session_state.pop("_collect_error", None)
if collect_err:
    st.error(f"자동 수집 오류: {collect_err}")
if st.session_state.pop("_collect_failed", False):
    st.warning("자동 수집 실패, 직접 붙여넣어 주세요.")

angle_err = st.session_state.pop("_angle_error", None)
if angle_err:
    st.error(f"각도 후보 뽑기 오류: {angle_err}")

_angle_candidates = st.session_state.get("angle_candidates", [])
if _angle_candidates:
    def _pick_angle():
        idx = st.session_state.get("angle_choice_idx")
        if isinstance(idx, int) and idx > 0:
            cands = st.session_state.get("angle_candidates", [])
            if idx - 1 < len(cands):
                st.session_state["focus_angle_input"] = cands[idx - 1]["title"]

    _labels = ["(선택 없음)"] + [
        f"{c['title']} — {c['explanation']}" for c in _angle_candidates
    ]
    st.radio(
        "각도 후보 (선택하면 위 '이번 편 집중 각도' 입력칸에 채워집니다)",
        options=list(range(len(_labels))),
        format_func=lambda i: _labels[i],
        key="angle_choice_idx",
        on_change=_pick_angle,
    )

references = st.text_area(
    "참고자료 (외교부 해외안전여행·대사관 공지 원문 붙여넣기)",
    height=220,
    key="references_input",
    placeholder="원문을 그대로 붙여넣으세요. 법률·처벌 서술은 이 자료에 근거가 있을 때만 쓰입니다.",
)
notes = st.text_area(
    "내가 아는 사실/관점 메모",
    height=160,
    placeholder="직접 겪었거나 확인한 사실, 강조하고 싶은 관점 등",
)

if not references.strip():
    st.warning("참고자료 없이 생성하면 법률 서술이 제외됩니다.")

submitted = st.button("초안 생성", type="primary")

if submitted and st.session_state.get("test_mode"):
    outs = list_outputs()
    if not outs:
        st.error("테스트 모드: outputs/ 에 저장된 파일이 없습니다.")
        st.stop()
    latest = outs[0]
    try:
        data = json.loads(latest.read_text(encoding="utf-8"))
    except Exception as e:
        st.error(f"테스트 모드 로드 실패: {e}")
        st.stop()
    st.info(f"테스트 모드: API 호출 없이 outputs/{latest.name} 를 불러왔습니다.")
    st.session_state["result"] = data
    st.session_state["loaded_from"] = latest.name
    submitted = False  # 아래 실제 생성 분기 스킵

if submitted:
    if not country.strip():
        st.error("나라 이름을 입력하세요.")
        st.stop()

    with st.spinner("생성 중..."):
        try:
            gen = generate(country, trip_type, references, notes, focus_angle)
        except ResponseParseError as e:
            st.error(f"응답을 JSON으로 파싱하지 못했습니다: {e}")
            if e.stop_reason == "max_tokens":
                st.warning(
                    "응답이 잘렸습니다 (stop_reason=max_tokens). "
                    "max_tokens 값을 더 크게 늘려주세요."
                )
            with st.expander("응답 원문 (원인 확인용)", expanded=True):
                st.code(e.raw_text or "(빈 응답)", language="json")
            st.stop()
        except Exception as e:
            st.error(f"생성 실패: {e}")
            st.stop()

    body_html_with_date = (
        f'{gen.get("body_html", "")}\n'
        f'<p>정보 확인일: {date.today().isoformat()}</p>'
    )
    verification_rows = run_verification(body_html_with_date, country)

    payload = {
        "country": country,
        "trip_type": trip_type,
        "focus_angle": focus_angle.strip(),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "titles": gen.get("titles", []),
        "body_html": body_html_with_date,
        "tags": gen.get("tags", []),
        "thumbnails": [
            t for t in gen.get("thumbnails", []) if isinstance(t, str) and t.strip()
        ],
        "verification_rows": verification_rows,
    }

    try:
        saved_path = save_output(payload)
        st.success(f"저장됨: outputs/{saved_path.name}")
    except Exception as e:
        st.warning(f"저장 실패: {e}")

    st.session_state["result"] = payload
    st.session_state.pop("loaded_from", None)

# 결과 렌더 (submit 직후이든, 사이드바에서 불러왔든 동일한 경로)
result = st.session_state.get("result")
if result:
    loaded_from = st.session_state.get("loaded_from")
    if loaded_from:
        st.info(f"저장된 초안 불러옴: outputs/{loaded_from}")
    render_result(result)
