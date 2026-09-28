"""
tests/test_validator.py — validator.py 단위 테스트.

실행: python3 -m unittest discover tests
외부 프레임워크: 표준 라이브러리 unittest 만 사용한다.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


TESTS_DIR = Path(__file__).resolve().parent
FIXTURES = TESTS_DIR / "fixtures"
TEST_TEMPLATES = FIXTURES / "test_templates.yaml"

# src 를 sys.path 에 추가해 validator 모듈을 임포트한다.
sys.path.insert(0, str(TESTS_DIR.parent / "src"))
import validator  # noqa: E402


def _validate(fixture_name: str) -> validator.Result:
    return validator.validate(FIXTURES / fixture_name, TEST_TEMPLATES)


def _fail_rule_ids(result: validator.Result) -> set[int]:
    return {f.rule_id for f in result.findings if f.level == "FAIL"}


class GoodFixtureTests(unittest.TestCase):
    def test_good_md_passes_all_rules(self) -> None:
        result = _validate("good.md")
        self.assertFalse(result.failed, msg=validator.format_report(FIXTURES / "good.md", result))
        # WARN 이 있어도 통과여야 한다 — 단, 프로덕션 기준으로 지적사항이 하나도 없어야 이상적이다.
        self.assertEqual(_fail_rule_ids(result), set())


class BadFixtureTests(unittest.TestCase):
    def test_bad_1_fails_opening(self) -> None:
        result = _validate("bad_1.md")
        self.assertTrue(result.failed)
        self.assertIn(1, _fail_rule_ids(result))

    def test_bad_4_fails_hidden_hook(self) -> None:
        result = _validate("bad_4.md")
        self.assertTrue(result.failed)
        self.assertIn(4, _fail_rule_ids(result))

    def test_bad_5_fails_cta(self) -> None:
        result = _validate("bad_5.md")
        self.assertTrue(result.failed)
        self.assertIn(5, _fail_rule_ids(result))

    def test_bad_6_fails_length(self) -> None:
        result = _validate("bad_6.md")
        self.assertTrue(result.failed)
        self.assertIn(6, _fail_rule_ids(result))

    def test_bad_7_fails_numbers_factcheck(self) -> None:
        result = _validate("bad_7.md")
        self.assertTrue(result.failed)
        self.assertIn(7, _fail_rule_ids(result))

    def test_bad_11_fails_title_count(self) -> None:
        result = _validate("bad_11.md")
        self.assertTrue(result.failed)
        self.assertIn(11, _fail_rule_ids(result))

    def test_bad_15_fails_video_source(self) -> None:
        result = _validate("bad_15.md")
        self.assertTrue(result.failed)
        self.assertIn(15, _fail_rule_ids(result))


if __name__ == "__main__":
    unittest.main()
