"""
db.py — SQLite (news.db) 접근 계층.

ORM 은 쓰지 않는다. 표준 sqlite3 만 사용한다.

스키마:
- articles: 수집한 기사 (naver_link 로 중복 판정)
- collection_runs: 한 번의 수집 실행 요약
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = ROOT / "news.db"


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS articles (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    naver_link     TEXT    NOT NULL UNIQUE,
    original_link  TEXT,
    title          TEXT    NOT NULL,
    description    TEXT,
    published_at   TEXT    NOT NULL,
    source         TEXT,
    query          TEXT,
    collected_at   TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_articles_published_at ON articles(published_at);

CREATE TABLE IF NOT EXISTS collection_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at          TEXT NOT NULL,
    total_queries   INTEGER,
    total_fetched   INTEGER,
    total_inserted  INTEGER,
    total_skipped   INTEGER
);
"""


@dataclass
class ArticleRow:
    """articles 에 넣거나 꺼낼 때 쓰는 값 묶음."""

    naver_link: str
    original_link: str
    title: str
    description: str
    published_at: str  # ISO 8601
    source: str
    query: str
    collected_at: str  # ISO 8601


def connect(db_path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """news.db 에 연결하고 필요한 초기 설정(외래키·row_factory)을 적용한다."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def open_db(db_path: Path | str = DEFAULT_DB_PATH) -> Iterator[sqlite3.Connection]:
    """with 블록 안에서 커밋/롤백을 자동 처리한다."""
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_schema(conn: sqlite3.Connection) -> None:
    """스키마를 만든다. 이미 있으면 그대로 둔다."""
    conn.executescript(SCHEMA_SQL)


def insert_article(conn: sqlite3.Connection, row: ArticleRow) -> bool:
    """
    articles 에 한 건 INSERT OR IGNORE.
    반환값:
        True  → 실제로 새 행이 추가됨
        False → 중복(naver_link) 이라 무시됨
    """
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO articles
            (naver_link, original_link, title, description,
             published_at, source, query, collected_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row.naver_link,
            row.original_link,
            row.title,
            row.description,
            row.published_at,
            row.source,
            row.query,
            row.collected_at,
        ),
    )
    return cur.rowcount == 1


def insert_run(
    conn: sqlite3.Connection,
    run_at: str,
    total_queries: int,
    total_fetched: int,
    total_inserted: int,
    total_skipped: int,
) -> int:
    """collection_runs 에 한 번의 실행 요약을 남긴다."""
    cur = conn.execute(
        """
        INSERT INTO collection_runs
            (run_at, total_queries, total_fetched, total_inserted, total_skipped)
        VALUES (?, ?, ?, ?, ?)
        """,
        (run_at, total_queries, total_fetched, total_inserted, total_skipped),
    )
    return int(cur.lastrowid)


def fetch_articles_since(
    conn: sqlite3.Connection, published_since_iso: str
) -> list[sqlite3.Row]:
    """지정 ISO 시각 이후로 발행된 기사를 최신순으로 반환한다."""
    cur = conn.execute(
        """
        SELECT id, naver_link, original_link, title, description,
               published_at, source, query, collected_at
        FROM articles
        WHERE published_at >= ?
        ORDER BY published_at DESC, id DESC
        """,
        (published_since_iso,),
    )
    return list(cur.fetchall())


def count_articles(conn: sqlite3.Connection) -> int:
    cur = conn.execute("SELECT COUNT(*) FROM articles")
    return int(cur.fetchone()[0])


def rows_to_export_dicts(rows: Iterable[sqlite3.Row]) -> list[dict]:
    """
    articles 행을 scorer 가 읽는 sample_articles.json 형식으로 변환한다.
    필드 매핑:
        id → "a{articles.id}"
        title → title
        body → description
        published_at → published_at
        url → original_link
        source → source
    """
    out: list[dict] = []
    for r in rows:
        out.append(
            {
                "id": f"a{r['id']}",
                "title": r["title"],
                "body": r["description"] or "",
                "published_at": r["published_at"],
                "url": r["original_link"] or r["naver_link"],
                "source": r["source"] or "",
            }
        )
    return out
