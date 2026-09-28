"""
scorer.py — 두 기사 페어링 채점기.

역할:
- pair_finder 로 페어 후보를 뽑고, categories.yaml 규칙에 따라 점수를 매긴다.
- 점수 = (카테고리 점수 + 페어링 강도) × 인물 가중치 + 프레임 보너스 + 감점
- 임계값: 80+ CONFIRMED, 50~79 CANDIDATE, <50 REJECTED

실행:
    python3 -m src.scorer <articles.json>
    → 콘솔 리포트 출력 + data/scored/YYYY-MM-DD.json 저장
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterable

import yaml

from .keyword_matcher import KeywordMatcher, load_keyword_config
from .pair_finder import Article, Pair, PairFinder, load_people, load_villains


ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"


# ---------- 카테고리 로더 ---------- #

@dataclass
class Category:
    id: str
    name: str
    score: int
    rank: int
    period_weight: float = 1.0
    keywords: list[str] = field(default_factory=list)


def load_categories(path: Path) -> list[Category]:
    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    out: list[Category] = []
    for group_key in ("categories", "lower_categories"):
        for entry in raw.get(group_key, []) or []:
            score = entry.get("score")
            if not isinstance(score, (int, float)):
                # TBD 등 확정되지 않은 카테고리는 건너뛴다.
                continue
            try:
                pw = float(entry.get("period_weight", 1.0))
            except (TypeError, ValueError):
                pw = 1.0
            out.append(
                Category(
                    id=str(entry.get("id", "")),
                    name=str(entry.get("name", "")),
                    score=int(score),
                    rank=int(entry.get("rank", 999)),
                    period_weight=pw,
                    keywords=[str(k) for k in entry.get("keywords", []) or []],
                )
            )
    return out


# ---------- 결과 모델 ---------- #

@dataclass
class ScoreBreakdown:
    category: int          # 카테고리 점수
    category_name: str     # 사람에게 보여줄 카테고리 이름
    pairing: int           # 페어링 강도 (키워드 개수 점수 + 시간 근접도)
    pairing_detail: str    # "키워드 15 + 시간 5" 같은 설명
    weight_multiplier: float
    weight_actor: str      # 가중치 적용 근거 인물명
    frame_bonus: int
    frame_labels: list[str]
    penalty: int
    penalty_reasons: list[str]

    def base(self) -> float:
        """(카테고리 점수 + 페어링 강도) — 인물 가중치가 곱해지는 대상."""
        return self.category + self.pairing

    def total(self) -> float:
        return self.base() * self.weight_multiplier + self.frame_bonus + self.penalty


@dataclass
class ScoreResult:
    rank: int
    pair: Pair
    score: float
    status: str  # CONFIRMED | CANDIDATE | REJECTED
    breakdown: ScoreBreakdown


# ---------- 채점기 ---------- #

class Scorer:
    def __init__(
        self,
        categories: list[Category],
        matcher: KeywordMatcher,
    ) -> None:
        self.categories = categories
        self.by_id = {c.id: c for c in categories}
        self.matcher = matcher

    def categorize(self, text: str) -> Category | None:
        """text 에서 매칭되는 카테고리 중 점수가 가장 높은 것을 반환한다."""
        hits: list[Category] = []
        for c in self.categories:
            if any(kw and kw in text for kw in c.keywords):
                hits.append(c)
        if not hits:
            return None
        # 같은 점수라면 rank 가 앞선(작은) 것을 우선한다.
        hits.sort(key=lambda c: (-c.score, c.rank))
        return hits[0]

    def _pairing_strength(self, pair: Pair) -> tuple[int, str]:
        """공통 키워드 × 5 (최대 25) + 시간 근접도(1일 이내 +10, 3일 이내 +5, 7일 이내 +0)."""
        kw_score = min(len(pair.common_keywords) * 5, 25)
        d = pair.day_diff
        if d <= 1:
            time_score = 10
        elif d <= 3:
            time_score = 5
        else:
            time_score = 0
        return kw_score + time_score, f"키워드 {kw_score} + 시간 {time_score}"

    def score_pair(self, pair: Pair) -> ScoreResult:
        # 카테고리 판정: A/B 각각 매칭, 점수가 높은 쪽 채택
        cat_a = self.categorize(pair.article_a.text)
        cat_b = self.categorize(pair.article_b.text)
        candidates = [c for c in (cat_a, cat_b) if c is not None]
        if candidates:
            chosen = max(candidates, key=lambda c: c.score)
            cat_score = chosen.score
            cat_name = chosen.name
            chosen_id = chosen.id
        else:
            cat_score = 0
            cat_name = "미분류"
            chosen_id = ""

        pairing_score, pairing_detail = self._pairing_strength(pair)

        # 인물 가중치: 페어의 protagonists 중 최대 weight
        weight = pair.top_protagonist_weight
        weight_actor = (
            pair.protagonists[0].name if pair.protagonists else "미상"
        )
        # 여러 명이면 실제로 최대 가중치를 낸 인물명을 찾는다
        if pair.protagonists:
            top = max(pair.protagonists, key=lambda p: p.weight)
            weight_actor = top.name
            weight = top.weight

        # 프레임 보너스
        frame_bonus, frame_labels = self.matcher.frame_bonus(
            pair.article_a.text, pair.article_b.text
        )

        # 감점
        penalty = 0
        reasons: list[str] = []
        # A 에 주인공/분신이 없고 단독 인물만 있으면 -30
        if not pair.protagonists:
            penalty -= 30
            reasons.append("A에 주인공/분신 없음 (단독 인물)")
        # B 의 악역 카테고리가 '여당 인물 비판'이면 -20
        if chosen_id == "ruling_party_critique":
            penalty -= 20
            reasons.append("B가 여당 인물 비판 카테고리")

        bd = ScoreBreakdown(
            category=cat_score,
            category_name=cat_name,
            pairing=pairing_score,
            pairing_detail=pairing_detail,
            weight_multiplier=weight,
            weight_actor=weight_actor,
            frame_bonus=frame_bonus,
            frame_labels=frame_labels,
            penalty=penalty,
            penalty_reasons=reasons,
        )

        total = bd.total()
        status = self._status_for(total)
        return ScoreResult(rank=0, pair=pair, score=total, status=status, breakdown=bd)

    def _status_for(self, score: float) -> str:
        if score >= 80:
            return "CONFIRMED"
        if score >= 50:
            return "CANDIDATE"
        return "REJECTED"

    def score_pairs(self, pairs: Iterable[Pair]) -> list[ScoreResult]:
        results = [self.score_pair(p) for p in pairs]
        results.sort(key=lambda r: r.score, reverse=True)
        for i, r in enumerate(results, start=1):
            r.rank = i
        return results


# ---------- 입출력 ---------- #

def load_articles(path: Path) -> list[Article]:
    with path.open(encoding="utf-8") as f:
        raw = json.load(f)
    if isinstance(raw, dict) and "articles" in raw:
        raw = raw["articles"]
    if not isinstance(raw, list):
        raise ValueError("articles JSON 은 배열 또는 {'articles': [...]} 형태여야 한다.")
    return [Article.from_dict(item) for item in raw]


def _fmt_date(dt) -> str:
    return dt.strftime("%m-%d")


def format_console(results: list[ScoreResult]) -> str:
    sep = "-" * 54
    lines = [sep]
    if not results:
        lines.append("페어 후보가 없습니다.")
        lines.append(sep)
        return "\n".join(lines)
    for r in results:
        a = r.pair.article_a
        b = r.pair.article_b
        bd = r.breakdown
        lines.append(f"[{r.rank}] 점수 {r.score:g} ({r.status})")
        lines.append(f"A: {a.title} ({a.source}, {_fmt_date(a.published_at)})")
        lines.append(f"B: {b.title} ({b.source}, {_fmt_date(b.published_at)})")
        kws = ", ".join(sorted(r.pair.common_keywords))
        lines.append(f"공통 키워드: {kws}")
        lines.append(f"카테고리: {bd.category_name} ({bd.category})")
        lines.append(f"페어링 강도: {bd.pairing} ({bd.pairing_detail})")
        lines.append(
            f"인물 가중치: ×{bd.weight_multiplier} ({bd.weight_actor})"
        )
        frames = ", ".join(bd.frame_labels) if bd.frame_labels else "없음"
        lines.append(f"프레임 보너스: +{bd.frame_bonus} ({frames})")
        if bd.penalty:
            reasons = "; ".join(bd.penalty_reasons)
            lines.append(f"감점: {bd.penalty} ({reasons})")
        else:
            lines.append("감점: 0")
        lines.append(sep)
    return "\n".join(lines)


def to_json_records(results: list[ScoreResult]) -> list[dict]:
    out: list[dict] = []
    for r in results:
        a = r.pair.article_a
        b = r.pair.article_b
        bd = r.breakdown
        out.append(
            {
                "rank": r.rank,
                "score": round(r.score, 2),
                "status": r.status,
                "article_a": {
                    "id": a.id,
                    "title": a.title,
                    "url": a.url,
                    "source": a.source,
                    "published_at": a.published_at.isoformat(),
                },
                "article_b": {
                    "id": b.id,
                    "title": b.title,
                    "url": b.url,
                    "source": b.source,
                    "published_at": b.published_at.isoformat(),
                },
                "common_keywords": sorted(r.pair.common_keywords),
                "day_diff": round(r.pair.day_diff, 2),
                "breakdown": {
                    "category": {
                        "score": bd.category,
                        "name": bd.category_name,
                    },
                    "pairing": {
                        "score": bd.pairing,
                        "detail": bd.pairing_detail,
                    },
                    "weight_multiplier": {
                        "value": bd.weight_multiplier,
                        "actor": bd.weight_actor,
                    },
                    "frame_bonus": {
                        "score": bd.frame_bonus,
                        "labels": bd.frame_labels,
                    },
                    "penalty": {
                        "score": bd.penalty,
                        "reasons": bd.penalty_reasons,
                    },
                },
            }
        )
    return out


def save_scored_json(results: list[ScoreResult], out_dir: Path, today: date) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{today.isoformat()}.json"
    payload = {
        "generated_at": today.isoformat(),
        "count": len(results),
        "pairs": to_json_records(results),
    }
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return out_path


# ---------- CLI ---------- #

def build_default_scorer() -> tuple[Scorer, PairFinder]:
    kw_cfg = load_keyword_config(CONFIG_DIR / "keywords.yaml")
    matcher = KeywordMatcher(kw_cfg)
    people = load_people(CONFIG_DIR / "people.yaml")
    villains = load_villains(CONFIG_DIR / "villains.yaml")
    categories = load_categories(CONFIG_DIR / "categories.yaml")
    finder = PairFinder(people=people, villains=villains, keyword_matcher=matcher)
    scorer = Scorer(categories=categories, matcher=matcher)
    return scorer, finder


def run(articles_path: Path, out_dir: Path | None = None) -> tuple[list[ScoreResult], Path]:
    scorer, finder = build_default_scorer()
    articles = load_articles(articles_path)
    pairs = finder.find_pairs(articles)
    results = scorer.score_pairs(pairs)

    out_dir = out_dir or (DATA_DIR / "scored")
    out_path = save_scored_json(results, out_dir, date.today())
    return results, out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="뉴스감지기 두 기사 페어링 채점기")
    parser.add_argument("articles", help="입력 기사 JSON 경로")
    parser.add_argument(
        "--out-dir",
        default=None,
        help="점수 JSON 저장 폴더 (기본: data/scored/)",
    )
    args = parser.parse_args(argv)

    articles_path = Path(args.articles)
    if not articles_path.exists():
        print(f"파일이 없습니다: {articles_path}", file=sys.stderr)
        return 2

    out_dir = Path(args.out_dir) if args.out_dir else None
    results, out_path = run(articles_path, out_dir=out_dir)
    print(format_console(results))
    print(f"결과 저장: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
