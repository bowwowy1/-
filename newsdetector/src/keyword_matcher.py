"""
keyword_matcher.py — 키워드 매칭과 프레임 감지 로직.

역할:
- config/keywords.yaml 에 등록된 관심 키워드를 기사 텍스트(제목 + 본문)에서 찾는다.
- 비교형·미스터리 프레임 표현도 같은 파일의 frames 섹션을 근거로 감지한다.

형태소 분석기를 쓰지 않는다. 단순 부분 문자열 매칭이다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import yaml


@dataclass
class FrameSpec:
    """프레임 하나(비교형·미스터리)의 감지 규칙."""

    key: str            # comparison | mystery
    label: str          # 사람에게 보여줄 라벨
    bonus: int          # 점수 보너스
    triggers: list[str] = field(default_factory=list)


@dataclass
class KeywordConfig:
    keywords: list[str]
    frames: list[FrameSpec]


def load_keyword_config(path: Path) -> KeywordConfig:
    """config/keywords.yaml 를 읽어 KeywordConfig 객체로 만든다."""
    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    keywords = [str(k).strip() for k in raw.get("keywords", []) if str(k).strip()]

    frames_raw = raw.get("frames", {}) or {}
    frames: list[FrameSpec] = []
    for key, spec in frames_raw.items():
        if not isinstance(spec, dict):
            continue
        frames.append(
            FrameSpec(
                key=str(key),
                label=str(spec.get("label", key)),
                bonus=int(spec.get("bonus", 0)),
                triggers=[str(t) for t in spec.get("triggers", []) if str(t).strip()],
            )
        )
    return KeywordConfig(keywords=keywords, frames=frames)


class KeywordMatcher:
    """관심 키워드 매칭과 프레임 감지."""

    def __init__(self, config: KeywordConfig) -> None:
        self.config = config

    def find_keywords(self, text: str) -> set[str]:
        """text 안에 등장하는 관심 키워드 집합을 돌려준다."""
        if not text:
            return set()
        return {kw for kw in self.config.keywords if kw in text}

    def common_keywords(self, text_a: str, text_b: str) -> set[str]:
        """두 텍스트에 동시에 등장하는 관심 키워드."""
        return self.find_keywords(text_a) & self.find_keywords(text_b)

    def detect_frames(self, text: str) -> list[FrameSpec]:
        """text 에서 감지된 프레임 목록. 여러 프레임이 감지되면 전부 반환한다."""
        hits: list[FrameSpec] = []
        if not text:
            return hits
        for frame in self.config.frames:
            if any(trigger in text for trigger in frame.triggers):
                hits.append(frame)
        return hits

    def frame_bonus(self, text_a: str, text_b: str) -> tuple[int, list[str]]:
        """
        두 기사 텍스트를 합쳐 프레임 감지, 보너스 합계와 감지된 프레임 라벨을 돌려준다.
        같은 프레임이 A/B 양쪽에서 감지돼도 한 번만 반영한다.
        """
        combined = f"{text_a}\n{text_b}"
        detected: dict[str, FrameSpec] = {}
        for f in self.detect_frames(combined):
            detected.setdefault(f.key, f)
        total = sum(f.bonus for f in detected.values())
        return total, [f.label for f in detected.values()]


def flatten_iter(*chunks: Iterable[str]) -> str:
    """제목·본문을 한 문자열로 합친다."""
    return "\n".join(str(c) for c in chunks if c)
