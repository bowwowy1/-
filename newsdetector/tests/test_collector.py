"""
tests/test_collector.py — 5단계 collector 단위 테스트.

pytest 로도 unittest 로도 실행된다 (unittest.TestCase 기반).
실제 HTTP 호출은 하지 않고 requests.get 을 mock 으로 대체한다.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock


TESTS_DIR = Path(__file__).resolve().parent
ROOT = TESTS_DIR.parent
sys.path.insert(0, str(ROOT))

from src import collector, db  # noqa: E402


class HtmlCleanTests(unittest.TestCase):
    """네이버 응답에 섞여 오는 <b> 태그와 HTML 엔티티를 지운다."""

    def test_strip_bold_tags(self) -> None:
        raw = "<b>이재명</b> 대통령, 국무회의서 <b>휴게소</b> 밥값 질타"
        self.assertEqual(
            collector.strip_html(raw),
            "이재명 대통령, 국무회의서 휴게소 밥값 질타",
        )

    def test_unescape_html_entities(self) -> None:
        raw = "&quot;도성회&quot; &amp; 도로공사 &#39;40년&#39; 특혜"
        self.assertEqual(
            collector.strip_html(raw),
            '"도성회" & 도로공사 \'40년\' 특혜',
        )

    def test_mixed_tags_and_entities(self) -> None:
        raw = "<b>&quot;참교육&quot;</b>&nbsp;시작"
        # &nbsp; 는 유니코드 non-breaking space 로 풀리고, 공백 정리로 일반 공백 하나가 된다.
        cleaned = collector.strip_html(raw)
        self.assertEqual(cleaned, '"참교육" 시작')


class PubdateConversionTests(unittest.TestCase):
    """네이버 pubDate 문자열을 ISO 8601 로 정규화한다."""

    def test_kst_pubdate(self) -> None:
        iso = collector.pubdate_to_iso("Mon, 15 Jan 2026 09:00:00 +0900")
        self.assertEqual(iso, "2026-01-15T09:00:00+09:00")

    def test_utc_pubdate(self) -> None:
        iso = collector.pubdate_to_iso("Thu, 01 Jan 2026 00:00:00 +0000")
        # +00:00 은 isoformat 에서 그대로 유지된다.
        self.assertEqual(iso, "2026-01-01T00:00:00+00:00")


class SourceExtractionTests(unittest.TestCase):
    """originallink 도메인에서 매체명을 뽑는다."""

    def test_known_domains(self) -> None:
        self.assertEqual(
            collector.source_from_originallink("https://n.news.naver.com/mnews/article/001/1"),
            "네이버",
        )
        self.assertEqual(
            collector.source_from_originallink("https://www.chosun.com/politics/2026/01/15/xxx/"),
            "조선일보",
        )
        self.assertEqual(
            collector.source_from_originallink("https://imnews.imbc.com/replay/2026/nw1400/xxx"),
            "MBC",
        )

    def test_subdomain_falls_back_to_registered(self) -> None:
        # sports.chosun.com 은 매핑에 없지만 chosun.com 매핑으로 되돌아간다.
        self.assertEqual(
            collector.source_from_originallink("https://sports.chosun.com/entertainment/xxx"),
            "조선일보",
        )

    def test_unknown_domain_returns_host(self) -> None:
        self.assertEqual(
            collector.source_from_originallink("https://example-news.co.kr/xxx"),
            "example-news.co.kr",
        )


class DbDuplicateTests(unittest.TestCase):
    """INSERT OR IGNORE: 같은 naver_link 를 두 번 넣으면 1건만 저장된다."""

    def _row(self, naver_link: str) -> db.ArticleRow:
        return db.ArticleRow(
            naver_link=naver_link,
            original_link="https://example.com/a",
            title="테스트 기사",
            description="테스트 본문",
            published_at="2026-01-15T09:00:00+09:00",
            source="테스트",
            query="테스트",
            collected_at="2026-01-15T10:00:00+09:00",
        )

    def test_insert_or_ignore_deduplicates(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.db"
            with db.open_db(path) as conn:
                db.init_schema(conn)
                inserted1 = db.insert_article(conn, self._row("https://n.news.naver.com/1"))
                inserted2 = db.insert_article(conn, self._row("https://n.news.naver.com/1"))
                total = db.count_articles(conn)
            self.assertTrue(inserted1)
            self.assertFalse(inserted2)
            self.assertEqual(total, 1)


class QueriesLoadTests(unittest.TestCase):
    """queries.yaml 로드 후 문자열 리스트를 얻는다."""

    def test_load_project_queries(self) -> None:
        queries = collector.load_queries()
        self.assertIsInstance(queries, list)
        # 사용자 스펙: 30~50개.
        self.assertGreaterEqual(len(queries), 30)
        self.assertLessEqual(len(queries), 50)
        # 대표 쿼리 몇 개가 들어 있는지 확인
        self.assertIn("이재명 국무회의", queries)
        self.assertIn("도성회", queries)


class ApiMockTests(unittest.TestCase):
    """requests.get 을 mock 으로 대체해 전체 수집 파이프라인이 도는지 확인한다."""

    def test_collect_query_with_mock(self) -> None:
        import tempfile

        # 네이버 API 가 돌려줄 가짜 응답 두 개(같은 link 하나 + 새 link 하나)
        fake_items = [
            {
                "title": "<b>이재명</b> 대통령, &quot;휴게소&quot; 질타",
                "originallink": "https://n.news.naver.com/aaa",
                "link": "https://n.news.naver.com/aaa",
                "description": "이재명 대통령이 <b>휴게소</b> 밥값을 지시했다.",
                "pubDate": "Mon, 15 Jan 2026 09:00:00 +0900",
            },
            {
                "title": "국토부 감사 결과 &#39;도성회&#39; 특혜",
                "originallink": "https://www.chosun.com/xxx",
                "link": "https://n.news.naver.com/bbb",
                "description": "감사 결과가 나왔다.",
                "pubDate": "Fri, 17 Jan 2026 08:30:00 +0900",
            },
        ]

        fake_response = MagicMock()
        fake_response.raise_for_status.return_value = None
        fake_response.json.return_value = {"items": fake_items}

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.db"
            with db.open_db(path) as conn:
                db.init_schema(conn)
                with patch("src.collector.requests.get", return_value=fake_response) as mocked:
                    result = collector.collect_query(
                        conn, "이재명 휴게소", client_id="X", client_secret="Y"
                    )
                self.assertEqual(mocked.call_count, 1)

            # 저장 결과 확인
            with db.open_db(path) as conn:
                total = db.count_articles(conn)

            self.assertEqual(result.fetched, 2)
            self.assertEqual(result.inserted, 2)
            self.assertEqual(result.skipped, 0)
            self.assertEqual(total, 2)


if __name__ == "__main__":
    unittest.main()
