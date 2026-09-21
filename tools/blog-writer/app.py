import html as html_lib
import json
import re
from datetime import date
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

PROMPT_PATH = Path(__file__).parent / "prompts" / "travel.txt"
MODEL_ID = "claude-sonnet-5"


def load_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def build_user_message(country: str, trip_type: str, references: str, notes: str) -> str:
    return (
        f"나라: {country}\n"
        f"여행 유형: {trip_type}\n\n"
        f"[참고자료 — 외교부 해외안전여행·대사관 공지 원문]\n{references or '(없음)'}\n\n"
        f"[내가 아는 사실/관점 메모]\n{notes or '(없음)'}\n\n"
        "아래 JSON 형식으로만 응답하라. 코드펜스나 다른 설명 없이 JSON 하나만 출력한다.\n"
        "{\n"
        '  "titles": ["제목 후보 10개, 문자열 배열"],\n'
        '  "body_html": "HTML 태그로 작성된 본문. <p>, <h3>, <ul>, <li> 등을 사용. 마크다운 금지.",\n'
        '  "tags": ["태그 15개, 문자열 배열. # 없이 단어만"]\n'
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


GENERATE_SCHEMA = {
    "type": "object",
    "properties": {
        "titles": {
            "type": "array",
            "items": {"type": "string"},
            "description": "제목 후보 10개",
        },
        "body_html": {
            "type": "string",
            "description": "HTML 태그로 작성된 본문. <p>, <h3>, <ul>, <li> 등 사용.",
        },
        "tags": {
            "type": "array",
            "items": {"type": "string"},
            "description": "태그 15개",
        },
    },
    "required": ["titles", "body_html", "tags"],
    "additionalProperties": False,
}

CLAIMS_SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["claims"],
    "additionalProperties": False,
}

VERIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["근거있음", "근거미발견", "상충"]},
        "sources": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
    },
    "required": ["verdict", "sources", "summary"],
    "additionalProperties": False,
}


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


def _parse_json_from_response(resp) -> dict:
    text_blocks = [b.text for b in resp.content if b.type == "text"]
    raw_text = "\n".join(text_blocks)
    stop_reason = getattr(resp, "stop_reason", None)

    for candidate in reversed(text_blocks):
        stripped = strip_code_fence(candidate)
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", stripped, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError:
                    continue

    match = re.search(r"\{.*\}", raw_text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError as e:
            raise ResponseParseError(str(e), raw_text, stop_reason)
    raise ResponseParseError("응답에서 JSON 객체를 찾지 못했습니다.", raw_text, stop_reason)


def _messages_create_json(client: Anthropic, *, schema: dict, schema_name: str, **kwargs):
    """messages.create + output_config json_schema. SDK가 output_config를
    지원하지 않으면 자동으로 폴백."""
    try:
        return client.messages.create(
            output_config={
                "format": {"type": "json_schema", "name": schema_name, "schema": schema}
            },
            **kwargs,
        )
    except TypeError:
        return client.messages.create(**kwargs)


def generate(country: str, trip_type: str, references: str, notes: str) -> dict:
    client = Anthropic()
    resp = _messages_create_json(
        client,
        schema=GENERATE_SCHEMA,
        schema_name="TravelDraft",
        model=MODEL_ID,
        max_tokens=16000,
        system=load_system_prompt(),
        messages=[{"role": "user", "content": build_user_message(country, trip_type, references, notes)}],
    )
    return _parse_json_from_response(resp)


def extract_legal_claims(body_html: str) -> list[str]:
    client = Anthropic()
    resp = _messages_create_json(
        client,
        schema=CLAIMS_SCHEMA,
        schema_name="LegalClaims",
        model=MODEL_ID,
        max_tokens=8000,
        system=(
            "너는 여행 블로그 본문에서 법률·처벌·규제와 관련된 사실 주장을 "
            "빠짐없이 모두 추출하는 도구다. 검증 대상이 될 수 있는 문장은 "
            "하나도 빠뜨리지 마라."
        ),
        messages=[{
            "role": "user",
            "content": (
                "아래 HTML 본문을 전체를 처음부터 끝까지 훑으며, 다음에 해당하는 "
                "모든 문장을 예외 없이 추출하라.\n"
                "\n"
                "포함 대상(하나라도 언급되면 반드시 포함):\n"
                "- 처벌 가능성 (체포, 구금, 기소, 추방 등)\n"
                "- 금지 행위 (해서는 안 되는 행동, 규정 위반)\n"
                "- 반입/반출 규제 (물품, 통화, 약품, 식품 등)\n"
                "- 벌금·과태료 액수\n"
                "- 형량 (징역, 금고 등 기간)\n"
                "- 비자·체류 관련 규정\n"
                "- 사진 촬영·복장·행위에 대한 법적 제약\n"
                "\n"
                "※ '※ 확인 필요' 표시가 붙은 문장은 정확성이 불확실한 문장이므로 "
                "  반드시 전부 포함해야 한다 (검증이 특히 필요한 대상).\n"
                "\n"
                "규칙:\n"
                "- HTML 태그는 제거하고 자연스러운 한 문장으로 정리한다.\n"
                "- 한 문단에 여러 주장이 있으면 각각 별도 항목으로 쪼갠다.\n"
                "- 문장 그 자체로 검증 가능해야 한다 (지시어 대체).\n"
                "- 요약하거나 다시 쓰지 말고, 원문의 사실 진술을 최대한 그대로 보존한다.\n"
                "- 개수 상한 없음. 해당하는 것은 모두 넣어라.\n"
                "\n"
                "JSON 하나만 응답. 다른 설명 금지.\n"
                '{"claims": ["문장1", "문장2", "문장3", ...]}\n\n'
                f"본문:\n{body_html}"
            ),
        }],
    )
    data = _parse_json_from_response(resp)
    return [c for c in data.get("claims", []) if isinstance(c, str) and c.strip()]


def verify_claim(claim: str) -> dict:
    client = Anthropic()
    resp = client.messages.create(
        model=MODEL_ID,
        max_tokens=8000,
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}],
        system=(
            "너는 여행자가 알아야 할 법률·처벌 주장을 정부·대사관·공신력 있는 "
            "기관(외교부, 현지 정부기관, 대사관 공지, 국제기구 등) 문서로 검증하는 "
            "도구다. 반드시 web_search 도구를 사용해 실제 출처를 찾아 판정하라."
        ),
        messages=[{
            "role": "user",
            "content": (
                "아래 주장을 검증하라.\n"
                '- 정부·대사관·공신력 있는 기관 문서에서 확인되면 verdict: "근거있음"\n'
                '- 신뢰할 만한 출처를 찾지 못하거나 확인이 안 되면 verdict: "근거미발견"\n'
                '- 신뢰할 만한 출처가 주장과 반대되면 verdict: "상충"\n'
                "sources 에는 실제로 확인한 URL만 넣어라. 없으면 빈 배열.\n"
                "summary 는 1~2문장으로 검색 근거를 요약하라. 확인이 안 되면 그 사유를.\n"
                "JSON 하나만 응답. 다른 설명 금지.\n"
                '{"verdict": "근거있음|근거미발견|상충", "sources": ["URL", ...], "summary": "요약"}\n\n'
                f"주장: {claim}"
            ),
        }],
    )
    data = _parse_json_from_response(resp)
    verdict = data.get("verdict", "근거미발견")
    if verdict not in ("근거있음", "근거미발견", "상충"):
        verdict = "근거미발견"
    return {
        "verdict": verdict,
        "sources": [s for s in data.get("sources", []) if isinstance(s, str)],
        "summary": data.get("summary", ""),
    }


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
        row_style = "color:#c92a2a;" if verdict == "근거미발견" else ""
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


st.set_page_config(page_title="여행 블로그 초안 생성기", layout="wide")
st.title("여행 블로그 초안 생성기")

with st.form("input_form"):
    country = st.text_input("나라 이름", placeholder="예: 튀르키예")
    trip_type = st.selectbox("여행 유형", ["관광", "출장", "장기체류"])
    references = st.text_area(
        "참고자료 (외교부 해외안전여행·대사관 공지 원문 붙여넣기)",
        height=220,
        placeholder="원문을 그대로 붙여넣으세요. 법률·처벌 서술은 이 자료에 근거가 있을 때만 쓰입니다.",
    )
    notes = st.text_area(
        "내가 아는 사실/관점 메모",
        height=160,
        placeholder="직접 겪었거나 확인한 사실, 강조하고 싶은 관점 등",
    )
    submitted = st.form_submit_button("초안 생성")

if submitted:
    if not country.strip():
        st.error("나라 이름을 입력하세요.")
        st.stop()

    with st.spinner("생성 중..."):
        try:
            result = generate(country, trip_type, references, notes)
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

    titles = result.get("titles", [])
    body_html = result.get("body_html", "")
    tags = result.get("tags", [])

    titles_text = "\n".join(f"{i}. {t}" for i, t in enumerate(titles, 1))
    tags_text = " ".join(f"#{tag}" for tag in tags)
    body_html_with_date = f'{body_html}\n<p>정보 확인일: {date.today().isoformat()}</p>'

    st.subheader("제목 후보 10개")
    render_copy_button("제목 복사", titles_text, None, key="titles")
    for i, title in enumerate(titles, 1):
        st.write(f"{i}. {title}")

    st.subheader("본문")
    body_html_for_clipboard = html_for_clipboard(body_html_with_date)
    render_copy_button("본문 복사 (서식 유지)", body_html_for_clipboard, body_html_for_clipboard, key="body")
    st.markdown(body_html_with_date, unsafe_allow_html=True)

    st.subheader("태그 15개")
    render_copy_button("태그 복사", tags_text, None, key="tags")
    st.write(tags_text)

    verification_header = st.empty()
    verification_header.subheader("법률 정보 검증")
    st.caption("본문은 자동으로 수정되지 않습니다. 검증 결과는 참고용으로만 표시합니다.")
    with st.spinner("본문에서 법률 관련 주장 추출 중..."):
        try:
            claims = extract_legal_claims(body_html)
        except ResponseParseError as e:
            st.error(f"주장 추출 응답을 JSON으로 파싱하지 못했습니다: {e}")
            if e.stop_reason == "max_tokens":
                st.warning("응답이 잘렸습니다 (stop_reason=max_tokens).")
            with st.expander("응답 원문 (원인 확인용)", expanded=True):
                st.code(e.raw_text or "(빈 응답)", language="json")
            claims = []
        except Exception as e:
            st.error(f"주장 추출 실패: {e}")
            claims = []

    verification_header.subheader(f"법률 정보 검증 ({len(claims)}건)")

    if not claims:
        st.info("본문에서 검증할 법률·처벌 관련 주장을 찾지 못했습니다.")
    else:
        rows: list[dict] = []
        progress = st.progress(0.0, text=f"검증 중 0/{len(claims)}")
        for i, claim in enumerate(claims):
            try:
                v = verify_claim(claim)
            except Exception as e:
                v = {"verdict": "근거미발견", "sources": [], "summary": f"(검증 오류) {e}"}
            rows.append({"claim": claim, **v})
            progress.progress((i + 1) / len(claims), text=f"검증 중 {i + 1}/{len(claims)}")
        progress.empty()
        render_verification_table(rows)
