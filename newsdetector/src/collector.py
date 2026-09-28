"""
collector.py — 네이버 뉴스 검색 API 로 기사를 수집해 news.db 에 저장한다.

실행: python3 -m src.collector

동작:
1. .env 에서 NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 로드
2. config/queries.yaml 에서 쿼리 목록 로드
3. 각 쿼리로 네이버 뉴스 API 호출 (display=100, sort=date), 호출 간 200ms 대기
4. 응답 정제: <b> 태그와 HTML 엔티티 제거, pubDate → ISO 8601, source 도메인 추출
5. articles 테이블에 INSERT OR IGNORE (naver_link 중복 시 스킵)
6. collection_runs 에 실행 요약 기록
"""

from __future__ import annotations

import argparse
import html as html_module
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

import requests
import yaml
from dotenv import load_dotenv

from .db import (
    ArticleRow,
    DEFAULT_DB_PATH,
    init_schema,
    insert_article,
    insert_run,
    open_db,
)


ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
QUERIES_PATH = CONFIG_DIR / "queries.yaml"

NAVER_ENDPOINT = "https://openapi.naver.com/v1/search/news.json"
DEFAULT_DISPLAY = 100
DEFAULT_SORT = "date"
CALL_INTERVAL_SEC = 0.2  # 호출 간 최소 200ms 대기

# 네이버 originallink 도메인 → 매체명 매핑 (매핑 없으면 도메인 기본형을 그대로 쓴다)
DOMAIN_TO_SOURCE: dict[str, str] = {
    "naver.com": "네이버",
    "n.news.naver.com": "네이버",
    "news.naver.com": "네이버",
    "chosun.com": "조선일보",
    "joongang.co.kr": "중앙일보",
    "donga.com": "동아일보",
    "hani.co.kr": "한겨레",
    "khan.co.kr": "경향신문",
    "hankyung.com": "한국경제",
    "mk.co.kr": "매일경제",
    "yna.co.kr": "연합뉴스",
    "yonhapnews.co.kr": "연합뉴스",
    "kbs.co.kr": "KBS",
    "imnews.imbc.com": "MBC",
    "mbc.co.kr": "MBC",
    "sbs.co.kr": "SBS",
    "jtbc.co.kr": "JTBC",
    "ytn.co.kr": "YTN",
    "seoul.co.kr": "서울신문",
    "hankookilbo.com": "한국일보",
    "kmib.co.kr": "국민일보",
    "segye.com": "세계일보",
    "sisain.co.kr": "시사IN",
    "kukinews.com": "쿠키뉴스",
    "ohmynews.com": "오마이뉴스",
    "pressian.com": "프레시안",
    "mediatoday.co.kr": "미디어오늘",
    "newsis.com": "뉴시스",
    "news1.kr": "뉴스1",
    "edaily.co.kr": "이데일리",
    "chosunbiz.com": "조선비즈",
    "biz.chosun.com": "조선비즈",
    "sedaily.com": "서울경제",
}


# ---------- 응답 정제 ---------- #

_TAG_RE = re.compile(r"<[^>]+>")


def strip_html(text: str) -> str:
    """
    네이버 응답의 title / description 에서 <b> 태그와 HTML 엔티티(&quot;, &amp; 등)를 제거한다.
    앞뒤 공백은 정리한다.
    """
    if not text:
        return ""
    # 1) 태그 제거
    no_tags = _TAG_RE.sub("", text)
    # 2) HTML 엔티티 (&amp;, &quot;, &#39; 등) 해제
    unescaped = html_module.unescape(no_tags)
    # 3) 연속 공백 정리
    return re.sub(r"\s+", " ", unescaped).strip()


def pubdate_to_iso(pubdate: str) -> str:
    """
    네이버 pubDate("Mon, 15 Jan 2026 09:00:00 +0900") 를 ISO 8601 로 변환한다.
    반환 예: "2026-01-15T09:00:00+09:00"
    """
    if not pubdate:
        return ""
    dt = parsedate_to_datetime(pubdate)
    if dt.tzinfo is None:
        # 네이버는 대체로 KST(+0900) 를 붙여 주지만, 안 붙어 있으면 UTC 로 간주한다.
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def source_from_originallink(original_link: str) -> str:
    """
    originallink 도메인에서 매체명을 뽑는다.
    매핑 표에 없으면 도메인의 "registered domain" 형태를 그대로 돌려준다.
    """
    if not original_link:
        return ""
    try:
        host = urlparse(original_link).hostname or ""
    except Exception:
        return ""
    host = host.lower()
    if host.startswith("www."):
        host = host[4:]

    if host in DOMAIN_TO_SOURCE:
        return DOMAIN_TO_SOURCE[host]

    # 서브도메인 매핑도 시도 (예: sports.chosun.com → chosun.com)
    parts = host.split(".")
    for start in range(len(parts) - 1):
        candidate = ".".join(parts[start:])
        if candidate in DOMAIN_TO_SOURCE:
            return DOMAIN_TO_SOURCE[candidate]

    return host


# ---------- API 호출 ---------- #

class MissingCredentials(RuntimeError):
    pass


def load_credentials(env_path: Path | None = None) -> tuple[str, str]:
    """.env 에서 NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 를 읽어 반환한다."""
    if env_path is not None:
        load_dotenv(dotenv_path=env_path)
    else:
        load_dotenv()
    cid = os.getenv("NAVER_CLIENT_ID", "").strip()
    csec = os.getenv("NAVER_CLIENT_SECRET", "").strip()
    if not cid or not csec:
        raise MissingCredentials(
            ".env 에 NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 가 없습니다. "
            ".env.example 을 참고해 프로젝트 루트에 .env 를 만들어 주세요."
        )
    return cid, csec


def load_queries(path: Path = QUERIES_PATH) -> list[str]:
    """queries.yaml 을 읽어 문자열 리스트로 돌려준다."""
    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    queries = raw.get("queries") or []
    out: list[str] = []
    for q in queries:
        if isinstance(q, str) and q.strip():
            out.append(q.strip())
    return out


def call_naver_api(
    query: str,
    client_id: str,
    client_secret: str,
    display: int = DEFAULT_DISPLAY,
    sort: str = DEFAULT_SORT,
    session: requests.Session | None = None,
) -> dict:
    """
    네이버 뉴스 검색 API 를 한 번 호출한다.
    HTTP 에러 시 예외를 그대로 던진다 (호출부에서 잡거나 로그로 남긴다).
    """
    headers = {
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret,
    }
    params = {"query": query, "display": display, "sort": sort}
    caller = session.get if session is not None else requests.get
    resp = caller(NAVER_ENDPOINT, headers=headers, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


# ---------- 수집 파이프라인 ---------- #

@dataclass
class QueryResult:
    query: str
    fetched: int
    inserted: int
    skipped: int


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _item_to_row(item: dict, query: str, collected_at: str) -> ArticleRow | None:
    """
    네이버 응답의 item 을 ArticleRow 로 변환한다. 필수 필드가 없으면 None.
    """
    naver_link = (item.get("link") or "").strip()
    if not naver_link:
        return None
    title = strip_html(item.get("title", ""))
    description = strip_html(item.get("description", ""))
    published_at = pubdate_to_iso(item.get("pubDate", ""))
    original_link = (item.get("originallink") or "").strip()
    source = source_from_originallink(original_link or naver_link)
    return ArticleRow(
        naver_link=naver_link,
        original_link=original_link,
        title=title,
        description=description,
        published_at=published_at,
        source=source,
        query=query,
        collected_at=collected_at,
    )


def collect_query(
    conn,
    query: str,
    client_id: str,
    client_secret: str,
    session: requests.Session | None = None,
) -> QueryResult:
    """
    한 쿼리에 대해 API 호출 → 정제 → INSERT OR IGNORE 를 수행하고 요약 반환.
    """
    payload = call_naver_api(query, client_id, client_secret, session=session)
    items = payload.get("items") or []
    fetched = len(items)
    inserted = 0
    skipped = 0
    collected_at = _now_iso()
    for item in items:
        row = _item_to_row(item, query, collected_at)
        if row is None:
            skipped += 1
            continue
        if insert_article(conn, row):
            inserted += 1
        else:
            skipped += 1
    return QueryResult(query=query, fetched=fetched, inserted=inserted, skipped=skipped)


def run_collection(
    queries: Iterable[str],
    client_id: str,
    client_secret: str,
    db_path: Path = DEFAULT_DB_PATH,
    call_interval: float = CALL_INTERVAL_SEC,
    session: requests.Session | None = None,
) -> tuple[list[QueryResult], int]:
    """
    전체 쿼리 목록을 돌린다. 반환: (쿼리별 결과 리스트, collection_runs 의 새 row id)
    """
    q_list = list(queries)
    total_queries = len(q_list)
    total_fetched = total_inserted = total_skipped = 0
    per_query: list[QueryResult] = []

    with open_db(db_path) as conn:
        init_schema(conn)
        for idx, query in enumerate(q_list, start=1):
            try:
                result = collect_query(conn, query, client_id, client_secret, session=session)
            except requests.HTTPError as e:
                print(f"[{idx}/{total_queries}] \"{query}\" 실패: HTTP {e.response.status_code}")
                per_query.append(QueryResult(query=query, fetched=0, inserted=0, skipped=0))
                if idx < total_queries:
                    time.sleep(call_interval)
                continue
            except requests.RequestException as e:
                print(f"[{idx}/{total_queries}] \"{query}\" 실패: {e}")
                per_query.append(QueryResult(query=query, fetched=0, inserted=0, skipped=0))
                if idx < total_queries:
                    time.sleep(call_interval)
                continue

            total_fetched += result.fetched
            total_inserted += result.inserted
            total_skipped += result.skipped
            per_query.append(result)

            dup_msg = f" (중복 {result.skipped}건 스킵)" if result.skipped else ""
            print(
                f"[{idx}/{total_queries}] \"{query}\" → {result.fetched}건 조회, "
                f"신규 {result.inserted}건 저장{dup_msg}"
            )

            if idx < total_queries:
                time.sleep(call_interval)

        run_id = insert_run(
            conn,
            run_at=_now_iso(),
            total_queries=total_queries,
            total_fetched=total_fetched,
            total_inserted=total_inserted,
            total_skipped=total_skipped,
        )

    print(
        f"\n총 {total_queries}개 쿼리, {total_fetched:,}건 조회, "
        f"신규 {total_inserted:,}건 저장 (run id={run_id})"
    )
    return per_query, run_id


# ---------- CLI ---------- #

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="네이버 뉴스 API 수집기")
    parser.add_argument(
        "--queries",
        default=str(QUERIES_PATH),
        help="쿼리 목록 yaml 경로 (기본: config/queries.yaml)",
    )
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB_PATH),
        help="SQLite DB 경로 (기본: news.db)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=CALL_INTERVAL_SEC,
        help="호출 간 대기(초). 최소 0.1 권장 (기본 0.2)",
    )
    args = parser.parse_args(argv)

    try:
        cid, csec = load_credentials()
    except MissingCredentials as e:
        print(str(e), file=sys.stderr)
        return 2

    queries = load_queries(Path(args.queries))
    if not queries:
        print(f"쿼리 목록이 비어 있습니다: {args.queries}", file=sys.stderr)
        return 2

    run_collection(
        queries,
        client_id=cid,
        client_secret=csec,
        db_path=Path(args.db),
        call_interval=max(0.1, float(args.interval)),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
