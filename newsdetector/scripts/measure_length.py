"""
measure_length.py — 정치한줄 대본 40개의 분량을 측정한다.

입력:
    newsdetector/data/benchmark/jeongchi_scripts.txt

파일 형식:
    각 대본은 "**번호. 제목 #해시태그**" 줄로 시작한다.
    본문이 이어지고, 끝에 [번호] 각주가 붙는다.

측정 규칙:
    - 제목 줄("**...**"), 해시태그(#...), [번호] 각주는 본문에서 제외한다.
    - 대본마다 공백 포함 글자 수, 공백 제외 글자 수를 센다.
    - 40개 대본 전체에 대해 평균, 중앙값, 최소, 최대, 하위 25%, 상위 75%를 낸다.

출력:
    - 표준 출력에 요약을 찍는다.
    - newsdetector/data/benchmark/length_stats.json 에 결과를 저장한다.
"""

from __future__ import annotations

import json
import re
import statistics
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
INPUT_PATH = ROOT / "data" / "benchmark" / "jeongchi_scripts.txt"
OUTPUT_PATH = ROOT / "data" / "benchmark" / "length_stats.json"

# 대본 시작 줄: "**1. 제목 #해시태그**" 형태
HEADER_RE = re.compile(r"^\s*\*\*\s*(\d+)\.\s*(.*?)\*\*\s*$")
# 각주: "[1]", "[12]"
FOOTNOTE_RE = re.compile(r"\[\d+\]")
# 해시태그: "#단어" (한글 포함)
HASHTAG_RE = re.compile(r"#\S+")


def split_scripts(raw: str) -> list[dict]:
    """헤더 줄을 기준으로 대본을 나눈다."""
    scripts: list[dict] = []
    current: dict | None = None
    for line in raw.splitlines():
        m = HEADER_RE.match(line)
        if m:
            if current is not None:
                scripts.append(current)
            current = {
                "number": int(m.group(1)),
                "title": m.group(2).strip(),
                "body_lines": [],
            }
        else:
            if current is not None:
                current["body_lines"].append(line)
    if current is not None:
        scripts.append(current)
    return scripts


def clean_body(lines: list[str]) -> str:
    """본문에서 해시태그, 각주를 제거하고 하나의 문자열로 합친다."""
    body = "\n".join(lines)
    body = HASHTAG_RE.sub("", body)
    body = FOOTNOTE_RE.sub("", body)
    return body


def count_chars(text: str) -> tuple[int, int]:
    """공백 포함, 공백 제외 글자 수를 반환한다."""
    with_space = len(text)
    without_space = len(re.sub(r"\s+", "", text))
    return with_space, without_space


def quartile(values: list[int], q: float) -> float:
    """
    q(0.0~1.0) 분위수를 선형 보간으로 계산한다.
    (파이썬 3.8+ statistics.quantiles 를 쓰지 않고 직접 구현해 이식성을 높였다.)
    """
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return float(s[0])
    pos = q * (len(s) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(s) - 1)
    frac = pos - lo
    return s[lo] + (s[hi] - s[lo]) * frac


def summarize(values: list[int]) -> dict:
    return {
        "count": len(values),
        "mean": round(statistics.mean(values), 2),
        "median": round(statistics.median(values), 2),
        "min": min(values),
        "max": max(values),
        "q1": round(quartile(values, 0.25), 2),
        "q3": round(quartile(values, 0.75), 2),
    }


def main() -> int:
    if not INPUT_PATH.exists():
        print(f"입력 파일이 없습니다: {INPUT_PATH}", file=sys.stderr)
        return 1

    raw = INPUT_PATH.read_text(encoding="utf-8")
    scripts = split_scripts(raw)
    if not scripts:
        print("대본을 찾지 못했습니다. 헤더 형식(**번호. 제목 #해시태그**)을 확인하세요.", file=sys.stderr)
        return 1

    per_script = []
    with_space_list: list[int] = []
    without_space_list: list[int] = []
    for s in scripts:
        body = clean_body(s["body_lines"])
        w, wo = count_chars(body)
        per_script.append(
            {
                "number": s["number"],
                "title": s["title"],
                "chars_with_space": w,
                "chars_without_space": wo,
            }
        )
        with_space_list.append(w)
        without_space_list.append(wo)

    stats = {
        "with_space": summarize(with_space_list),
        "without_space": summarize(without_space_list),
        "per_script": per_script,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    ws = stats["with_space"]
    wos = stats["without_space"]
    print(f"측정한 대본 수: {ws['count']}")
    print("--- 공백 포함 ---")
    print(f"  평균  {ws['mean']}  / 중앙값 {ws['median']}")
    print(f"  최소  {ws['min']}  / 최대   {ws['max']}")
    print(f"  하위25% {ws['q1']} / 상위75% {ws['q3']}")
    print("--- 공백 제외 ---")
    print(f"  평균  {wos['mean']}  / 중앙값 {wos['median']}")
    print(f"  최소  {wos['min']}  / 최대   {wos['max']}")
    print(f"  하위25% {wos['q1']} / 상위75% {wos['q3']}")
    print(f"결과 저장: {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
