"""
pair_finder.py — 두 기사 페어링 판정 로직.

정치한줄 공식 A(두 기사 접합)를 코드로 옮긴다.
- 기사 A: 주인공(이재명) 또는 분신(여권 단체장·대통령실·내각) 쪽 기사.
- 기사 B: 악역(villains.yaml 유형) 쪽 기사.
- 두 기사가 아래 4조건을 만족하면 페어 후보다.
    1. A 텍스트에 people.yaml 의 protagonist/proxies 인물명이 1개 이상 등장
    2. B 텍스트에 villains.yaml 의 악역 유형 키워드가 1개 이상 등장
    3. published_at 차이가 7일 이내
    4. A ∩ B 공통 대상 키워드가 1개 이상 (keywords.yaml 기반)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable

import yaml

from .keyword_matcher import KeywordMatcher, flatten_iter


PROTAGONIST_GROUPS = ("protagonist", "proxies", "cabinet")
OPPONENT_GROUPS = ("opponents",)


# ---------- 데이터 모델 ---------- #

@dataclass
class Article:
    id: str
    title: str
    body: str
    published_at: datetime
    url: str = ""
    source: str = ""

    @property
    def text(self) -> str:
        return flatten_iter(self.title, self.body)

    @classmethod
    def from_dict(cls, d: dict) -> "Article":
        pub = d["published_at"]
        if isinstance(pub, str):
            # ISO 형식만 지원. 'Z' 접미사도 처리.
            pub = pub.replace("Z", "+00:00")
            dt = datetime.fromisoformat(pub)
        elif isinstance(pub, datetime):
            dt = pub
        else:
            raise ValueError(f"알 수 없는 published_at 형식: {pub!r}")
        return cls(
            id=str(d["id"]),
            title=str(d.get("title", "")),
            body=str(d.get("body", "")),
            published_at=dt,
            url=str(d.get("url", "")),
            source=str(d.get("source", "")),
        )


@dataclass
class PersonHit:
    name: str
    role: str
    weight: float
    position: str = ""


@dataclass
class VillainHit:
    type: str          # opposition_local_head 등
    label: str         # "국민의힘 단체장" 등
    matched_via: str   # 매칭에 사용된 키워드 또는 인물명


@dataclass
class Pair:
    article_a: Article
    article_b: Article
    protagonists: list[PersonHit]
    villains: list[VillainHit]
    common_keywords: set[str]
    day_diff: float

    @property
    def top_protagonist_weight(self) -> float:
        """A 에 등장한 분신 인물 중 가장 큰 weight (없으면 1.0)."""
        if not self.protagonists:
            return 1.0
        return max(p.weight for p in self.protagonists)


# ---------- 로더 ---------- #

@dataclass
class PeopleConfig:
    protagonists: list[PersonHit] = field(default_factory=list)
    proxies: list[PersonHit] = field(default_factory=list)
    cabinet: list[PersonHit] = field(default_factory=list)
    opponents: list[PersonHit] = field(default_factory=list)

    def all_hero_side(self) -> list[PersonHit]:
        return self.protagonists + self.proxies + self.cabinet

    def all_opponents(self) -> list[PersonHit]:
        return self.opponents


def _to_person(entry: dict, default_role: str) -> PersonHit | None:
    name = str(entry.get("name", "")).strip()
    if not name or name == "TBD":
        return None
    try:
        weight = float(entry.get("weight", 1.0))
    except (TypeError, ValueError):
        weight = 1.0
    return PersonHit(
        name=name,
        role=str(entry.get("role", default_role)),
        weight=weight,
        position=str(entry.get("position", "")),
    )


def load_people(path: Path) -> PeopleConfig:
    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    cfg = PeopleConfig()
    for entry in raw.get("protagonist", []) or []:
        p = _to_person(entry, "protagonist")
        if p:
            cfg.protagonists.append(p)
    for entry in raw.get("proxies", []) or []:
        p = _to_person(entry, "proxy")
        if p:
            cfg.proxies.append(p)
    for entry in raw.get("cabinet", []) or []:
        p = _to_person(entry, "cabinet")
        if p:
            cfg.cabinet.append(p)
    for entry in raw.get("opponents", []) or []:
        p = _to_person(entry, "opponent")
        if p:
            cfg.opponents.append(p)
    return cfg


@dataclass
class VillainType:
    type: str
    label: str
    description: str
    examples: list[str] = field(default_factory=list)
    match_keywords: list[str] = field(default_factory=list)


# 각 villain type 을 텍스트에서 검출하기 위한 표층 키워드 매핑.
# villains.yaml 은 label·description·examples 만 두므로, 여기서는 그것들과 함께
# 실무적으로 텍스트에 나올 만한 표현을 함께 매칭 대상으로 삼는다.
_VILLAIN_KEYWORDS: dict[str, list[str]] = {
    "opposition_local_head": ["국민의힘 단체장", "국힘 단체장", "국민의힘 시장", "국민의힘 도지사"],
    "opposition_local_council": ["국힘 지방의회", "국민의힘 지방의회", "국힘 시의회", "국민의힘 시의회", "국힘 도의회", "국민의힘 도의회"],
    "opposition_leadership": ["국민의힘 지도부", "국힘 지도부", "국민의힘 당대표", "국힘 원내대표"],
    "uncooperative_bureaucrat": ["공무원", "기관장", "지시 불이행", "말 안 듣는 공무원"],
    "judiciary": ["사법부", "판사", "검찰"],
    "media": ["언론", "조중동"],
    "cartel_group": ["카르텔", "도성회", "협회", "퇴직자 모임", "이권 카르텔"],
    "foreign_japan": ["일본", "다카이치"],
    "vague_forces": ["일부 세력", "비판하는 사람들"],
    "chaebol_hostile": ["쿠팡"],
}


def load_villains(path: Path) -> list[VillainType]:
    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    out: list[VillainType] = []
    for entry in raw.get("villains", []) or []:
        t = str(entry.get("type", "")).strip()
        if not t:
            continue
        examples = [str(e) for e in entry.get("examples", []) or []]
        # examples 중 괄호 앞 부분만 뽑아서 매칭 후보에 넣는다 (예: "도성회 (도로공사 퇴직자 모임)" → "도성회").
        example_names = []
        for ex in examples:
            head = ex.split("(")[0].strip()
            if head:
                example_names.append(head)
        out.append(
            VillainType(
                type=t,
                label=str(entry.get("label", t)),
                description=str(entry.get("description", "")),
                examples=examples,
                match_keywords=_VILLAIN_KEYWORDS.get(t, []) + example_names,
            )
        )
    return out


def load_opponent_names(people_cfg: PeopleConfig) -> list[str]:
    """opponents 그룹의 실제 인물명(오세훈·박완수 등)을 반환한다.
    악역 매칭 시 이 이름들도 추가 매칭 키워드로 사용한다."""
    return [p.name for p in people_cfg.opponents if p.name]


# ---------- 페어 판정 ---------- #

class PairFinder:
    def __init__(
        self,
        people: PeopleConfig,
        villains: list[VillainType],
        keyword_matcher: KeywordMatcher,
        day_window: int = 7,
    ) -> None:
        self.people = people
        self.villains = villains
        self.matcher = keyword_matcher
        self.day_window = day_window
        self._opponent_names = load_opponent_names(people)

    def find_protagonists(self, text: str) -> list[PersonHit]:
        """text 에 등장하는 주인공/분신 인물 목록."""
        hits: list[PersonHit] = []
        for person in self.people.all_hero_side():
            if person.name and person.name in text:
                hits.append(person)
        return hits

    def find_villains(self, text: str) -> list[VillainHit]:
        """text 에 등장하는 악역 유형 목록. 각 유형은 최대 1회 반환한다."""
        hits: list[VillainHit] = []
        seen: set[str] = set()
        for villain in self.villains:
            for kw in villain.match_keywords:
                if kw and kw in text and villain.type not in seen:
                    hits.append(VillainHit(type=villain.type, label=villain.label, matched_via=kw))
                    seen.add(villain.type)
                    break
        # 국힘 개별 광역단체장 이름 (오세훈 등) 이 나와도 opposition_local_head 로 분류한다.
        if "opposition_local_head" not in seen:
            for opp_name in self._opponent_names:
                if opp_name and opp_name in text:
                    hits.append(
                        VillainHit(
                            type="opposition_local_head",
                            label="국민의힘 단체장",
                            matched_via=opp_name,
                        )
                    )
                    seen.add("opposition_local_head")
                    break
        return hits

    def _pair_check(self, a: Article, b: Article) -> Pair | None:
        prots = self.find_protagonists(a.text)
        if not prots:
            return None
        vils = self.find_villains(b.text)
        if not vils:
            return None
        delta = abs((a.published_at - b.published_at).total_seconds()) / 86400
        if delta > self.day_window:
            return None
        common = self.matcher.common_keywords(a.text, b.text)
        if not common:
            return None
        return Pair(
            article_a=a,
            article_b=b,
            protagonists=prots,
            villains=vils,
            common_keywords=common,
            day_diff=delta,
        )

    def find_pairs(self, articles: Iterable[Article]) -> list[Pair]:
        """전체 기사 목록에서 페어 후보를 모두 찾는다.
        (i, j) 를 뒤집어서 (j, i) 도 시도한다. 각 기사가 A/B 양쪽 다 될 수 있다."""
        arts = list(articles)
        seen: set[tuple[str, str]] = set()
        results: list[Pair] = []
        for i, a in enumerate(arts):
            for j, b in enumerate(arts):
                if i == j:
                    continue
                key = (a.id, b.id)
                if key in seen:
                    continue
                pair = self._pair_check(a, b)
                if pair is not None:
                    results.append(pair)
                    seen.add(key)
        return results
