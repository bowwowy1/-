"""
validator.py — 뉴스감지기 대본·제목·영상 소스 린터.

입력:
    output/YYYY-MM-DD/<소재명>.md
    (CLAUDE.md 에 정의된 출력 파일 형식을 따르는 마크다운)

실행:
    python3 src/validator.py <파일경로>

규칙 값(문구, 분량, 단어 목록)은 config/templates.yaml 에서 읽는다.
외부 라이브러리는 pyyaml 만 사용한다.

FAIL: 규칙 1~7, 11~15 위반 → 종료 코드 1.
WARN: 규칙 8~10 (인과 표현, 단정 표현, 분량 근접 위반) → 결과에만 표시.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TEMPLATES = ROOT / "config" / "templates.yaml"


# ---------- 데이터 모델 ---------- #

@dataclass
class Section:
    heading: str
    lines: list[str] = field(default_factory=list)

    @property
    def body(self) -> str:
        return "\n".join(self.lines).strip()


@dataclass
class Finding:
    rule_id: int
    level: str  # "FAIL" or "WARN"
    label: str
    detail: str = ""


@dataclass
class Result:
    findings: list[Finding] = field(default_factory=list)

    def add(self, rule_id: int, level: str, label: str, detail: str = "") -> None:
        self.findings.append(Finding(rule_id, level, label, detail))

    @property
    def failed(self) -> bool:
        return any(f.level == "FAIL" for f in self.findings)


# ---------- 파서 ---------- #

HEADING_RE = re.compile(r"^##\s+(.+?)\s*$")


def parse_sections(text: str) -> dict[str, Section]:
    """마크다운을 ## 헤딩 기준으로 분리한다."""
    sections: dict[str, Section] = {}
    current: Section | None = None
    for raw in text.splitlines():
        m = HEADING_RE.match(raw)
        if m:
            heading = m.group(1).strip()
            current = Section(heading=heading)
            sections[heading] = current
        else:
            if current is not None:
                current.lines.append(raw)
    return sections


def find_section(sections: dict[str, Section], keyword: str) -> Section | None:
    for heading, sec in sections.items():
        if keyword in heading:
            return sec
    return None


# ---------- 대본 검사 ---------- #

SENTENCE_END_RE = re.compile(r"(?<=[\.!?。])\s+|(?<=다)\s+|(?<=요)\s+")
# 숫자 표현 검출:
#  - 단일자 한글 숫자(일/이/삼/사/오/육/칠/팔/구)는 일상어와 충돌(이건, 이 일 등)해서 제외한다.
#  - 명확한 다중자 앵커(십/백/천/만/억/조)만 한글 숫자로 인정한다.
NUMBER_UNITS = (
    "억원|만원|천원|원|%|퍼센트|명|곳|년|월|일|시간|분|초|건|번|위|호|배"
)
ARABIC_NUMBER_RE = re.compile(
    rf"\d[\d,\.]*(?:\s*[천백만억조])*\s*(?:{NUMBER_UNITS})"
)
KOREAN_NUMBER_RE = re.compile(
    rf"(?:십|백|천|만|억|조)(?:\s*[천백만억조])?\s*(?:{NUMBER_UNITS})"
)
CAUSATION_TOKENS = ("덕분에", "때문에", "결국")
CAUSATION_PATTERN_RE = re.compile(r"[가-힣]+해서\s+[가-힣]+됐")
ABSOLUTE_TOKENS = ("100%", "무조건", "전부", "모든")


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[\.!?])\s+|\n+", text)
    return [p.strip() for p in parts if p.strip()]


def _first_sentence(text: str) -> str:
    text = text.strip()
    if not text:
        return ""
    m = re.search(r"[\.!?\n]", text)
    return text[: m.end()].strip() if m else text.strip()


def extract_numbers(text: str) -> list[str]:
    hits: list[str] = []
    for m in ARABIC_NUMBER_RE.finditer(text):
        hits.append(m.group(0).strip())
    for m in KOREAN_NUMBER_RE.finditer(text):
        hits.append(m.group(0).strip())
    return hits


def check_script(
    script_body: str, factcheck_text: str, length_cfg: dict, phrases: dict, result: Result
) -> None:
    body = script_body.strip()

    # 규칙 1: 첫 문장이 "이거 사실이야?" 로 시작
    opening = phrases.get("opening", "이거 사실이야?")
    first = _first_sentence(body)
    if not first.startswith(opening):
        result.add(1, "FAIL", "오프닝 고정 문구", f"첫 문장이 '{opening}' 로 시작하지 않음. 첫 문장: '{first[:40]}'")

    # 규칙 2: 전환 문구가 앞 30% 안에 있음
    transition = phrases.get("transition", "무슨 내용인지 바로 알려줄게")
    idx_transition = body.find(transition)
    threshold_30 = int(len(body) * 0.30)
    if idx_transition < 0:
        result.add(2, "FAIL", "전환 문구 위치", f"'{transition}' 가 대본에 없음")
    elif idx_transition > threshold_30:
        result.add(
            2,
            "FAIL",
            "전환 문구 위치",
            f"'{transition}' 가 앞 30% 밖에 있음 (위치 {idx_transition}/{len(body)})",
        )

    # 규칙 3: "근데" 가 전환 문구 뒤에 1회 이상
    if idx_transition >= 0:
        tail = body[idx_transition + len(transition):]
        if "근데" not in tail:
            result.add(3, "FAIL", "반전 접속사", "'근데' 가 전환 문구 뒤에 없음")
    else:
        result.add(3, "FAIL", "반전 접속사", "전환 문구가 없어 '근데' 위치를 검사할 수 없음")

    # 규칙 4: "이건 몰랐지?" 가 정확히 1회, "근데" 뒤에 나옴
    twist_hook = phrases.get("twist_hook", "이건 몰랐지?")
    count_hook = body.count(twist_hook)
    if count_hook != 1:
        result.add(4, "FAIL", "'이건 몰랐지?' 등장 횟수", f"정확히 1회여야 하나 {count_hook}회 등장")
    else:
        idx_geunde = body.find("근데")
        idx_hook = body.find(twist_hook)
        if idx_geunde < 0 or idx_hook < idx_geunde:
            result.add(4, "FAIL", "'이건 몰랐지?' 순서", "'근데' 뒤에 있어야 함")

    # 규칙 5: 마지막 문장에 CTA 포함
    cta_tail = "구독과 좋아요 부탁하고 여러분의 생각을 댓글로 남겨주세요"
    if cta_tail not in body[-len(cta_tail) - 40:]:
        result.add(5, "FAIL", "고정 CTA", "마지막 문장에 고정 CTA가 없음")

    # 규칙 6/10: 분량 검사 (공백 포함)
    tmin = length_cfg.get("target_min")
    tmax = length_cfg.get("target_max")
    length = len(body)
    if isinstance(tmin, (int, float)) and isinstance(tmax, (int, float)):
        if tmin <= length <= tmax:
            pass
        else:
            # ±5% 안이면 WARN
            near_min = tmin * 0.95
            near_max = tmax * 1.05
            if near_min <= length <= near_max:
                result.add(
                    10,
                    "WARN",
                    "분량 근접 위반",
                    f"길이 {length} 자, 목표 {tmin}~{tmax} 자에서 ±5% 안",
                )
            else:
                result.add(
                    6,
                    "FAIL",
                    "분량 범위",
                    f"길이 {length} 자, 목표 {tmin}~{tmax} 자 (공백 포함) 밖",
                )
    else:
        result.add(
            6,
            "WARN",
            "분량 범위 미확정",
            f"templates.yaml length 가 확정되지 않음 (target_min={tmin}, target_max={tmax}). 길이 {length} 자.",
        )

    # 규칙 7: 대본 속 숫자가 팩트체크 목록에 URL 과 함께 있음
    numbers = extract_numbers(body)
    unique_numbers = []
    seen = set()
    for n in numbers:
        norm = re.sub(r"\s+", "", n)
        if norm not in seen:
            seen.add(norm)
            unique_numbers.append(n)
    missing_numbers: list[str] = []
    for n in unique_numbers:
        norm = re.sub(r"\s+", "", n)
        norm_fc = re.sub(r"\s+", "", factcheck_text)
        # 팩트체크 목록 안에서 숫자 표현이 등장하고, 같은 라인/근접 위치에 http 링크가 있어야 통과
        found_with_link = False
        for line in factcheck_text.splitlines():
            line_norm = re.sub(r"\s+", "", line)
            if norm in line_norm and re.search(r"https?://", line):
                found_with_link = True
                break
        if not found_with_link:
            missing_numbers.append(n)
    if missing_numbers:
        result.add(
            7,
            "FAIL",
            "숫자 팩트체크",
            f"대본 속 숫자 중 팩트체크 목록에 URL 이 없는 항목: {', '.join(missing_numbers)}",
        )

    # 규칙 8 (WARN): 인과 표현 문장 목록
    causation_sentences: list[str] = []
    for sent in split_sentences(body):
        if any(tok in sent for tok in CAUSATION_TOKENS) or CAUSATION_PATTERN_RE.search(sent):
            causation_sentences.append(sent)
    if causation_sentences:
        detail = " | ".join(s[:60] for s in causation_sentences)
        result.add(8, "WARN", "인과 표현 확인 대상", detail)

    # 규칙 9 (WARN): 단정 표현
    absolute_hits: list[str] = []
    for tok in ABSOLUTE_TOKENS:
        if tok in body:
            absolute_hits.append(tok)
    if absolute_hits:
        result.add(9, "WARN", "단정 표현 확인 대상", ", ".join(absolute_hits))


# ---------- 제목 검사 ---------- #

TITLE_HASHTAGS = ("#이재명", "#더불어민주당")


def parse_title_candidates(section_body: str) -> list[str]:
    """
    제목 후보 3개 섹션에서 후보 문자열을 뽑는다.
    - "- ", "1.", "1)" 등으로 시작하는 줄을 후보로 인식한다.
    """
    candidates: list[str] = []
    for raw in section_body.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = re.match(r"^(?:[-*]|\d+[\.\)])\s+(.*)$", line)
        if m:
            candidates.append(m.group(1).strip())
    return candidates


def _first_word(title: str) -> str:
    m = re.match(r"\s*(\S+)", title)
    return m.group(1) if m else ""


def check_titles(title_section_body: str, factcheck_text: str, result: Result) -> None:
    cands = parse_title_candidates(title_section_body)

    # 규칙 11: 정확히 3개
    if len(cands) != 3:
        result.add(11, "FAIL", "제목 후보 수", f"정확히 3개여야 하나 {len(cands)}개")
        # 개수 오류여도 나머지 검사 계속

    # 규칙 12: 세 후보의 훅(첫 어절) 이 서로 다름
    if len(cands) >= 2:
        hooks = [_first_word(c) for c in cands]
        if len(set(hooks)) != len(hooks):
            result.add(12, "FAIL", "제목 훅 중복", f"첫 어절이 중복: {hooks}")

    # 규칙 13: 각 후보에 필수 해시태그 포함
    for i, c in enumerate(cands, start=1):
        missing = [h for h in TITLE_HASHTAGS if h not in c]
        if missing:
            result.add(
                13,
                "FAIL",
                f"제목 #{i} 필수 해시태그 누락",
                f"'{', '.join(missing)}' 누락 → {c}",
            )

    # 규칙 14: 제목 속 숫자도 팩트체크 대상
    for i, c in enumerate(cands, start=1):
        for n in extract_numbers(c):
            norm = re.sub(r"\s+", "", n)
            ok = False
            for line in factcheck_text.splitlines():
                line_norm = re.sub(r"\s+", "", line)
                if norm in line_norm and re.search(r"https?://", line):
                    ok = True
                    break
            if not ok:
                result.add(
                    14,
                    "FAIL",
                    f"제목 #{i} 숫자 팩트체크",
                    f"'{n}' 이 팩트체크 목록에 URL 없이 등장",
                )


# ---------- 영상 소스 검사 ---------- #

ALLOWED_CHANNELS = ("JTBC 뉴스", "MBC 뉴스", "JTBC뉴스", "MBC뉴스")


def parse_video_lines(body: str) -> list[str]:
    lines: list[str] = []
    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            continue
        if re.match(r"^(?:[-*]|\d+[\.\)])\s+", line):
            lines.append(line)
    return lines


def check_videos(video_body: str, result: Result) -> None:
    entries = parse_video_lines(video_body)
    count = len(entries)

    # 규칙 15: 3~5개, JTBC 뉴스 / MBC 뉴스만
    if not (3 <= count <= 5):
        result.add(15, "FAIL", "영상 개수", f"3~5개여야 하나 {count}개")

    bad_channels: list[str] = []
    for entry in entries:
        if not any(ch in entry for ch in ALLOWED_CHANNELS):
            bad_channels.append(entry[:60])
    if bad_channels:
        result.add(
            15,
            "FAIL",
            "영상 채널 제한",
            f"JTBC 뉴스/MBC 뉴스가 아닌 항목: {' | '.join(bad_channels)}",
        )


# ---------- 파이프라인 ---------- #

def load_templates(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def validate(md_path: Path, templates_path: Path) -> Result:
    text = md_path.read_text(encoding="utf-8")
    sections = parse_sections(text)
    cfg = load_templates(templates_path)
    length_cfg = cfg.get("length") or {}
    phrases = cfg.get("fixed_phrases") or {}

    result = Result()

    script_sec = find_section(sections, "대본")
    title_sec = find_section(sections, "제목 후보")
    video_sec = find_section(sections, "영상 소스")
    fact_sec = find_section(sections, "사실 확인")

    factcheck_body = fact_sec.body if fact_sec else ""

    if script_sec is None:
        result.add(0, "FAIL", "구조", "'## 대본' 섹션이 없음")
    else:
        check_script(script_sec.body, factcheck_body, length_cfg, phrases, result)

    if title_sec is None:
        result.add(0, "FAIL", "구조", "'## 제목 후보 3개' 섹션이 없음")
    else:
        check_titles(title_sec.body, factcheck_body, result)

    if video_sec is None:
        result.add(0, "FAIL", "구조", "'## 영상 소스' 섹션이 없음")
    else:
        check_videos(video_sec.body, result)

    return result


def format_report(md_path: Path, result: Result) -> str:
    lines = [f"파일: {md_path}"]
    if result.failed:
        lines.append("결과: FAIL")
    else:
        lines.append("결과: PASS")
    if not result.findings:
        lines.append("  (지적 사항 없음)")
    for f in result.findings:
        lines.append(f"  [{f.level}] 규칙 {f.rule_id:>2} · {f.label}")
        if f.detail:
            lines.append(f"          → {f.detail}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="뉴스감지기 대본·제목·영상 소스 린터")
    parser.add_argument("path", help="검사할 마크다운 파일 경로")
    parser.add_argument(
        "--templates",
        default=str(DEFAULT_TEMPLATES),
        help="config/templates.yaml 경로 (기본: 프로젝트 기본값)",
    )
    args = parser.parse_args(argv)

    md_path = Path(args.path)
    if not md_path.exists():
        print(f"파일이 없습니다: {md_path}", file=sys.stderr)
        return 2

    result = validate(md_path, Path(args.templates))
    print(format_report(md_path, result))
    return 1 if result.failed else 0


if __name__ == "__main__":
    sys.exit(main())
