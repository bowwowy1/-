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
    "description": "생성한 여행 블로그 초안 (제목 후보 10개, HTML 본문, 태그 15개)을 제출한다.",
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
                "description": "HTML 태그(<p>, <h3>, <ul>, <li> 등)로 작성된 본문. 마크다운 금지.",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "태그 문자열 15개 (# 없이 단어만).",
                "minItems": 15,
                "maxItems": 15,
            },
        },
        "required": ["titles", "body_html", "tags"],
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


def generate(country: str, trip_type: str, references: str, notes: str) -> dict:
    client = Anthropic()
    resp = client.messages.create(
        model=MODEL_ID,
        max_tokens=16000,
        system=load_system_prompt(),
        messages=[{"role": "user", "content": build_user_message(country, trip_type, references, notes)}],
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
            "너는 여행 블로그 본문에서 법률·처벌·규제와 관련된 사실 주장을 "
            "빠짐없이 모두 추출하는 도구다. 검증 대상이 될 수 있는 문장은 "
            "하나도 빠뜨리지 마라. 반드시 submit_legal_claims 도구를 호출해 "
            "결과를 제출하라."
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
                "- 개수 상한 없음. 해당하는 것은 모두 넣어라.\n\n"
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


def verify_claim(claim: str) -> dict:
    """web_search + submit_verdict 다중 tool 루프. 최대 3회 반복.
    검색된 URL이 없으면 verdict 를 '근거미발견'으로 강제한다."""
    client = Anthropic()
    system_prompt = (
        "너는 여행자가 알아야 할 법률·처벌 주장을 정부·대사관·공신력 있는 "
        "기관(외교부, 현지 정부기관, 대사관 공지, 국제기구 등) 문서로 검증하는 "
        "도구다.\n"
        "\n"
        "필수 순서:\n"
        "1) 먼저 web_search 도구로 실제 출처를 검색한다.\n"
        "2) 검색 결과를 근거로 submit_verdict 도구를 호출해 최종 판정을 제출한다.\n"
        "\n"
        "엄격한 규칙:\n"
        "- 사전 지식만으로는 절대 '근거있음' 판정을 내리지 마라.\n"
        "- web_search 결과에 신뢰할 만한 URL이 없으면 verdict 는 반드시 '근거미발견'.\n"
        "- 검색이 충분하다고 판단되면 반드시 submit_verdict 를 호출해 마무리하라."
    )
    messages: list[dict] = [{
        "role": "user",
        "content": (
            "아래 주장을 검증하라. 반드시 web_search 로 먼저 조사한 뒤 "
            "submit_verdict 로 결과를 넘겨라.\n"
            "- 정부·대사관·공신력 있는 기관 문서에서 확인되면 verdict: 근거있음\n"
            "- 신뢰할 만한 출처를 찾지 못하거나 확인이 안 되면 verdict: 근거미발견\n"
            "- 신뢰할 만한 출처가 주장과 반대되면 verdict: 상충\n"
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
        VERIFY_LIMIT = 6
        # "※ 확인 필요" 가 붙은 주장을 우선. 원래 순서 유지 (안정 정렬).
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
                v = verify_claim(claim)
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

        render_verification_table(rows)
