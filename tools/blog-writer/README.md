# 여행 블로그 초안 생성기

Streamlit 로컬 앱. 나라 이름·여행 유형·참고자료·메모를 입력하면
Anthropic API(`claude-sonnet-5`)로 제목 후보 10개, HTML 본문, 태그 15개를 생성한다.

## 구성

```
tools/blog-writer/
  app.py                Streamlit UI + Anthropic API 호출
  prompts/travel.txt    시스템 프롬프트 (코드와 분리)
  requirements.txt      streamlit, anthropic, python-dotenv
  .env.example          ANTHROPIC_API_KEY 템플릿
```

## 실행

```bash
cd tools/blog-writer
pip install -r requirements.txt
cp .env.example .env      # ANTHROPIC_API_KEY 입력
streamlit run app.py
```

`.env`는 `app.py`가 있는 디렉터리에서 읽는다. 다른 위치에서 `streamlit run`을
띄우려면 `ANTHROPIC_API_KEY`를 셸 환경변수로 export 하거나 해당 디렉터리로
이동한 뒤 실행한다.

## 동작

- 입력: 나라 이름, 여행 유형(관광/출장/장기체류), 참고자료(외교부
  해외안전여행·대사관 공지 원문), 내가 아는 사실/관점 메모
- 출력: 제목 후보 10개 / HTML 본문(`st.markdown(unsafe_allow_html=True)`로
  렌더링) / 태그 15개
- 프롬프트 규칙(섹션 구조, 금지 표현, 확인 필요 표기 등)은
  `prompts/travel.txt`에 정의되어 있으며 코드에서 하드코딩하지 않는다.
