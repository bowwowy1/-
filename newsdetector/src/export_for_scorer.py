"""
export_for_scorer.py — news.db 에서 최근 N일치 기사를 scorer 가 읽는 형식으로 내보낸다.

실행:
    python3 -m src.export_for_scorer --days 3

결과:
    data/collected/YYYY-MM-DD.json
    (data/sample_articles.json 과 동일한 필드 구조)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .db import (
    DEFAULT_DB_PATH,
    fetch_articles_since,
    open_db,
    rows_to_export_dicts,
)


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT_DIR = ROOT / "data" / "collected"


def export(
    days: int,
    db_path: Path = DEFAULT_DB_PATH,
    out_dir: Path = DEFAULT_OUT_DIR,
    now: datetime | None = None,
) -> Path:
    """
    최근 `days` 일 동안 published_at 이 찍힌 기사를 뽑아
    data/collected/YYYY-MM-DD.json 으로 저장한다.
    """
    if days <= 0:
        raise ValueError("--days 는 1 이상이어야 합니다.")
    if now is None:
        now = datetime.now(timezone.utc).astimezone()
    since = (now - timedelta(days=days)).isoformat()

    with open_db(db_path) as conn:
        rows = fetch_articles_since(conn, since)

    payload = {"articles": rows_to_export_dicts(rows)}
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{now.date().isoformat()}.json"
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="news.db 에서 최근 N일치 기사를 scorer 입력 JSON 으로 내보낸다."
    )
    parser.add_argument("--days", type=int, default=3, help="최근 며칠 (기본 3)")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite DB 경로")
    parser.add_argument(
        "--out-dir", default=str(DEFAULT_OUT_DIR), help="출력 폴더 (기본: data/collected/)"
    )
    args = parser.parse_args(argv)

    try:
        out_path = export(
            days=args.days,
            db_path=Path(args.db),
            out_dir=Path(args.out_dir),
        )
    except FileNotFoundError:
        print(f"DB 파일이 없습니다: {args.db}. 먼저 collector 를 실행하세요.", file=sys.stderr)
        return 2
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2

    # 저장한 파일의 건수를 요약 출력
    with out_path.open(encoding="utf-8") as f:
        n = len(json.load(f).get("articles", []))
    print(f"최근 {args.days}일치 기사 {n}건을 {out_path} 로 저장했습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
