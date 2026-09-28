# 뉴스감지기

정치·시사 유튜브 숏츠 채널 "뉴스감지기"의 소재 발굴·대본 검증·영상 소스 추천을 돕는 도구.

## 개요
- 채널명: 뉴스감지기
- 형식: 정치·시사 숏츠
- 시청층: 40~70대
- 성향: 친이재명
- 현재 구독자: 약 600명
- 벤치마킹 대상: 구독자 27만 "정치한줄"

## 최종 목표
소재 1건당 세 가지를 `output/YYYY-MM-DD/<소재명>.md` 파일 하나로 뽑는다.
썸네일은 사람이 직접 만들기 때문에 범위에서 뺀다.

1. 대본: 8단계 규칙을 따르고 `validator` 를 통과한 것
2. 제목 후보 3개: `docs/title_rules.md` 를 따른다
3. 영상 소스 추천: JTBC 뉴스와 MBC뉴스 공식 유튜브 채널의 영상만, 3~5개

출력 파일에는 소재 요약, 기사 짝(A/B), 대본, 제목 후보 3개, 영상 소스, 사실 확인 목록이 들어간다.

## 구성
- `docs/` — 기준 문서 (프로젝트의 근거)
  - `channel.md` — 채널 정체성, 벤치마킹 원칙, 저작권 규칙
  - `script_rules.md` — 대본 8단계 규칙
  - `sourcing.md` — 소재 발굴 규칙
  - `title_rules.md` — 제목 공식
- `config/` — 인물, 카테고리, 스토리 공식, 악역, 대본 템플릿 yaml
- `data/benchmark/` — 정치한줄 대본과 썸네일 데이터
- `scripts/` — 벤치마크 측정 스크립트 (`measure_length.py`)
- `src/`
  - `validator.py` — 대본 린터 (3단계)
  - `scorer.py` — 기사 짝 채점기 (4단계)
  - `writer.py` — 대본·제목 작성 지시서 생성기 (5단계)
  - `video_finder.py` — YouTube 영상 추천기 (6단계)
  - `collector.py` — 뉴스 수집기 (7단계)
- `output/` — 소재별 최종 산출물 (`YYYY-MM-DD/<소재명>.md`)
- `tests/` — 테스트

## 개발 단계
1. **1단계 (완료)**: 프로젝트 뼈대와 기준 문서
2. **1.5단계**: 최종 목표와 단계 계획 문서화
3. **2단계**: `config/` yaml 채우기 (분량 확정 포함)
4. **3단계**: `src/validator.py` 구현 (대본 린터)
5. **4단계**: `src/scorer.py` 구현 (기사 짝 채점기)
6. **5단계**: `src/writer.py` — 작성 지시서 생성기
   - 별도 API 없이, Claude Code 세션이 그 지시서로 대본과 제목을 쓴다.
   - 결과는 `validator.py` 로 자동 검사한다.
7. **6단계**: `src/video_finder.py` — YouTube Data API v3 로 영상 추천
   - `.env` 의 `YOUTUBE_API_KEY` 사용
   - 채널은 JTBC 뉴스(@jtbc_news)와 MBC뉴스(@MBCNEWS11) 두 개만
   - 채널 ID 는 `forHandle` 로 조회해 `config/video_sources.yaml` 에 저장 (실패 시 중단)
   - 최근 30일 영상 우선, 대본 단계 매핑, 하루 할당량 관리
8. **7단계**: `src/collector.py` 연결과 하루 1회 실행 흐름
   - 수집 → 채점 → 작성 지시서 → 대본·제목 → 검사 → 영상 추천 → `output/` 저장

## 요구사항
- Python 3
- 의존성: `pyyaml` (`requirements.txt` 참고)
- 환경 변수: `YOUTUBE_API_KEY` (`.env.example` 참고, 6단계부터 필요)

## 작업 기준
`CLAUDE.md` 를 먼저 읽는다. 모든 결정의 근거는 `docs/` 다.
