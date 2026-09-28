"""
scorer.py — 소재 채점기.

4단계에서 구현한다. 지금은 자리만 잡는다.

역할:
- docs/sourcing.md 의 "소재 3조건"(구도, 확인된 고리, 카테고리)을 기준으로
  후보 소재에 점수를 매긴다.
- config/categories.yaml 의 서열과 score 를 사용한다.
- config/formulas.yaml 의 스토리 공식 A~E 중 어떤 것에 해당하는지 태깅한다.
- config/people.yaml 의 역할군과 weight 를 반영한다.
- 두 기사 접합(A) 가능 여부를 확인한다.
"""

# TODO(4단계): config 로더(categories.yaml, formulas.yaml, people.yaml, villains.yaml) 구현
# TODO(4단계): 후보 소재 데이터 모델 정의
#   - 기사 A(주인공 쪽), 기사 B(악역 쪽), 인물, 카테고리, 확인된 고리
# TODO(4단계): 3조건 체크 구현
#   1) 구도: 주인공 vs 상대가 한 문장으로 나오는가, 상대 얼굴이 있는가
#   2) 확인된 고리: 기사 A·B 를 잇는 사실이 기사로 확인되는가
#   3) 카테고리: 서열 상위(1~5)에 드는가
# TODO(4단계): 카테고리 점수, 인물 weight, 공식 매치 여부를 합산해 최종 점수 산출
# TODO(4단계): 공식 A~E 태깅기 구현
# TODO(4단계): 결과 랭킹·필터 출력
