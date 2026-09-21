import json
from datetime import date
from pathlib import Path

import streamlit as st
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


def generate(country: str, trip_type: str, references: str, notes: str) -> dict:
    client = Anthropic()
    resp = client.messages.create(
        model=MODEL_ID,
        max_tokens=16000,
        system=load_system_prompt(),
        messages=[{"role": "user", "content": build_user_message(country, trip_type, references, notes)}],
    )
    text = "".join(block.text for block in resp.content if block.type == "text")
    return json.loads(strip_code_fence(text))


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
        except json.JSONDecodeError as e:
            st.error(f"응답을 JSON으로 파싱하지 못했습니다: {e}")
            st.stop()
        except Exception as e:
            st.error(f"생성 실패: {e}")
            st.stop()

    titles = result.get("titles", [])
    body_html = result.get("body_html", "")
    tags = result.get("tags", [])

    st.subheader("제목 후보 10개")
    for i, title in enumerate(titles, 1):
        st.write(f"{i}. {title}")

    st.subheader("본문")
    body_html_with_date = f'{body_html}\n<p>정보 확인일: {date.today().isoformat()}</p>'
    st.markdown(body_html_with_date, unsafe_allow_html=True)

    st.subheader("태그 15개")
    st.write(" ".join(f"#{tag}" for tag in tags))
