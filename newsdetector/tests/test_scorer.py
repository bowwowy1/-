"""
tests/test_scorer.py — 4단계 scorer.py 단위 테스트.

pytest 로 실행: `python3 -m pytest tests/test_scorer.py`
unittest 로 실행: `python3 -m unittest tests.test_scorer` (같은 케이스가 발견된다)

외부 프레임워크 없이 표준 unittest.TestCase 만 사용한다.
pytest 는 unittest.TestCase 도 인식하므로 두 러너 모두에서 동작한다.
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path


TESTS_DIR = Path(__file__).resolve().parent
ROOT = TESTS_DIR.parent

# 프로젝트 루트를 sys.path 에 추가해 `import src.xxx` 가 되게 한다.
sys.path.insert(0, str(ROOT))

from src.keyword_matcher import KeywordMatcher, load_keyword_config  # noqa: E402
from src.pair_finder import Article, PairFinder, load_people, load_villains  # noqa: E402
from src.scorer import Scorer, load_categories  # noqa: E402


CONFIG_DIR = ROOT / "config"


def _make_article(
    aid: str,
    title: str,
    body: str,
    published_at: datetime,
    source: str = "테스트",
) -> Article:
    return Article(
        id=aid,
        title=title,
        body=body,
        published_at=published_at,
        url=f"https://example.com/{aid}",
        source=source,
    )


def _build_scorer_and_finder() -> tuple[Scorer, PairFinder]:
    kw_cfg = load_keyword_config(CONFIG_DIR / "keywords.yaml")
    matcher = KeywordMatcher(kw_cfg)
    people = load_people(CONFIG_DIR / "people.yaml")
    villains = load_villains(CONFIG_DIR / "villains.yaml")
    categories = load_categories(CONFIG_DIR / "categories.yaml")
    finder = PairFinder(people=people, villains=villains, keyword_matcher=matcher)
    scorer = Scorer(categories=categories, matcher=matcher)
    return scorer, finder


class NormalPairTests(unittest.TestCase):
    """정상 페어가 CONFIRMED 로 판정되는지 확인한다."""

    def test_president_and_cartel_pair_is_confirmed(self) -> None:
        scorer, finder = _build_scorer_and_finder()
        a = _make_article(
            "a",
            "이재명 대통령, 국무회의서 휴게소 밥값 질타",
            "대통령이 국토부와 도로공사에 지시했다. 카르텔이 문제다.",
            datetime(2026, 1, 15, 9, 0),
            source="연합뉴스",
        )
        b = _make_article(
            "b",
            "국토부 감사 결과 '도성회 40년 휴게소 특혜'",
            "도로공사 퇴직자 모임 도성회가 카르텔로 특혜를 챙긴 감사 결과가 나왔다.",
            datetime(2026, 1, 17, 8, 30),
            source="한겨레",
        )
        pairs = finder.find_pairs([a, b])
        self.assertEqual(len(pairs), 1)
        result = scorer.score_pair(pairs[0])
        self.assertEqual(result.status, "CONFIRMED")
        self.assertGreaterEqual(result.score, 80)


class TimeWindowTests(unittest.TestCase):
    """시간 창(7일) 초과 시 페어가 성립하지 않는다."""

    def test_pair_outside_seven_days_is_not_paired(self) -> None:
        _, finder = _build_scorer_and_finder()
        a = _make_article(
            "a",
            "이재명 대통령, 방산 순방 성과",
            "이재명 대통령의 방산 순방 소식과 예산 편성 계획이 이어졌다.",
            datetime(2026, 1, 8, 16, 0),
        )
        b = _make_article(
            "b",
            "방산 관련 국민의힘 지도부 반발",
            "국민의힘 지도부가 방산 예산 관련 카르텔 의혹을 제기했다.",
            datetime(2026, 1, 20, 9, 0),  # 12일 차
        )
        pairs = finder.find_pairs([a, b])
        self.assertEqual(pairs, [])


class NoCommonKeywordTests(unittest.TestCase):
    """공통 대상 키워드가 없으면 페어가 성립하지 않는다."""

    def test_pair_without_common_keyword_is_not_paired(self) -> None:
        _, finder = _build_scorer_and_finder()
        a = _make_article(
            "a",
            "이재명 대통령, 순방 성과 발표",
            "대통령이 이번 순방으로 국무회의에서 성과를 정리한다.",
            datetime(2026, 1, 15, 9, 0),
        )
        b = _make_article(
            "b",
            "축구협회 비리 감사 결과 공개",
            "축구협회가 갑질과 특혜로 카르텔을 운영해 온 정황이 드러났다.",
            datetime(2026, 1, 16, 9, 0),
        )
        pairs = finder.find_pairs([a, b])
        self.assertEqual(pairs, [])


class PersonWeightMultiplierTests(unittest.TestCase):
    """A 에 등장한 분신 인물의 weight 가 (카테고리 + 페어링) 에만 곱해진다."""

    def test_person_weight_multiplies_base_only(self) -> None:
        scorer, _ = _build_scorer_and_finder()
        # 김상욱(weight 1.5) 이 등장하는 A
        a = _make_article(
            "a",
            "김상욱 울산시장, 지방의회 예산 삭감 반대",
            "김상욱 시장이 울산시의회 예산 삭감에 반대하며 회견을 열었다.",
            datetime(2026, 1, 14, 11, 0),
        )
        b = _make_article(
            "b",
            "울산 시의회 국민의힘, 예산 부결",
            "국민의힘 지방의회가 예산을 부결시켰다. 감사 요구가 이어진다.",
            datetime(2026, 1, 15, 9, 30),
        )
        scorer2, finder = _build_scorer_and_finder()
        pairs = finder.find_pairs([a, b])
        self.assertEqual(len(pairs), 1)
        r = scorer2.score_pair(pairs[0])
        bd = r.breakdown
        # 곱셈은 (카테고리 + 페어링) 에만 적용된다.
        expected = bd.base() * bd.weight_multiplier + bd.frame_bonus + bd.penalty
        self.assertAlmostEqual(r.score, expected)
        self.assertEqual(bd.weight_actor, "김상욱")
        self.assertAlmostEqual(bd.weight_multiplier, 1.5)


class FrameBonusTests(unittest.TestCase):
    """비교형·미스터리 프레임 감지 시 보너스가 붙는다."""

    def test_comparison_and_mystery_frame_bonus(self) -> None:
        scorer, finder = _build_scorer_and_finder()
        a = _make_article(
            "a",
            "이재명 대통령, 인사 결정… 이 타이밍에 왜?",
            "돌연 인사 카드가 나왔다. 윤석열 때는 없었던 지시가 나왔다.",
            datetime(2026, 1, 16, 13, 0),
        )
        b = _make_article(
            "b",
            "국민의힘 지도부, 인사 지연에 반발",
            "국민의힘 지도부가 인사 절차의 감사 결과를 요구하고 있다.",
            datetime(2026, 1, 17, 9, 0),
        )
        pairs = finder.find_pairs([a, b])
        self.assertEqual(len(pairs), 1)
        r = scorer.score_pair(pairs[0])
        # 비교형(+10) + 미스터리(+15) = +25
        self.assertGreaterEqual(r.breakdown.frame_bonus, 25)
        labels = set(r.breakdown.frame_labels)
        self.assertIn("비교형 프레임", labels)
        self.assertIn("미스터리 프레임", labels)


class SoloPersonPenaltyTests(unittest.TestCase):
    """주인공/분신이 없이 단독 인물만 있는 A 는 페어가 안 되지만,
    score_pair 를 직접 태우면 -30 감점이 적용된다."""

    def test_solo_person_penalty_applies_when_no_protagonist(self) -> None:
        scorer, _ = _build_scorer_and_finder()
        # protagonist/proxy 가 아닌 인물로만 구성된 pair 를 강제로 만든다
        from src.pair_finder import Pair, VillainHit

        a = _make_article(
            "a",
            "김철수 시장, 예산 편성 발표",
            "김철수 시장이 예산 편성 카드를 꺼냈다.",
            datetime(2026, 1, 15, 9, 0),
        )
        b = _make_article(
            "b",
            "국민의힘 지도부, 예산안 반대",
            "국민의힘 지도부가 예산안에 반대했다. 감사 요구도 있다.",
            datetime(2026, 1, 16, 9, 0),
        )
        pair = Pair(
            article_a=a,
            article_b=b,
            protagonists=[],  # A 에 주인공/분신 없음
            villains=[VillainHit(type="opposition_leadership", label="국민의힘 지도부", matched_via="국민의힘 지도부")],
            common_keywords={"예산"},
            day_diff=1.0,
        )
        r = scorer.score_pair(pair)
        self.assertLessEqual(r.breakdown.penalty, -30)
        self.assertTrue(
            any("주인공/분신 없음" in reason for reason in r.breakdown.penalty_reasons)
        )


if __name__ == "__main__":
    unittest.main()
