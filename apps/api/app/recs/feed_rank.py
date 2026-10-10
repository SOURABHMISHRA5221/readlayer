"""For you feed ranking (M7.5 §A.5, DESIGN §17). Pure: no I/O, no SDK, no LLM.

score = interest(topic) × format_affinity(format) × readiness × goal_boost × freshness

- interest: the reader's stored domain interest, normalised so their top topic is 1.0;
- format_affinity: the existing per-reader format model (`rank.format_affinity`);
- readiness: how many ideas the item names that are new to this reader (exact label/alias
  matches over 1–4-word n-grams of its title and snippet): 1–4 new → 1.0, none → 0.6, more
  than 4 → 0.8^(k−4) (too much at once);
- goal_boost: 1.3 when the item names a learning-goal target concept;
- freshness: `rank.freshness`.
"""

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime

from app.graph.graph import ConceptGraph
from app.graph.models import Concept
from app.graph.taxonomy import BY_ID
from app.reader import model
from app.reader.state import ReaderState
from app.recs.models import Format, WebResult
from app.recs.rank import FormatPrior, FormatStats, format_affinity, freshness

READY_MIN, READY_MAX = 1, 4
NOTHING_NEW = 0.6
TOO_MUCH_DECAY = 0.8
GOAL_BOOST = 1.3
MAX_ITEMS = 24
QUOTAS: Mapping[Format, int] = {"article": 3, "video": 2, "podcast": 1}
NGRAM_MAX = 4
ARTICLE_MAX_AGE = timedelta(days=14)
_WORDS = re.compile(r"[\w'’&-]+", re.UNICODE)


@dataclass(frozen=True)
class FeedCandidate:
    result: WebResult
    topic: str  # taxonomy domain id
    concepts: tuple[Concept, ...] = ()


@dataclass(frozen=True)
class RankedItem:
    candidate: FeedCandidate
    score: float
    new_concepts: tuple[str, ...]  # labels new to this reader
    goal_label: str | None
    why: str


@dataclass(frozen=True)
class FeedReader:
    """What ranking needs to know about the reader, all in memory."""

    state: ReaderState
    interest: Mapping[str, float]  # domain → stored interest
    prior: FormatPrior
    stats: Mapping[Format, FormatStats] = field(default_factory=dict)
    goal_targets: Mapping[str, str] = field(default_factory=dict)  # concept id → goal label


def named_concepts(graph: ConceptGraph, text: str) -> tuple[Concept, ...]:
    """Graph concepts the text names: exact label/alias match over 1–4-word n-grams, longest
    first, without overlapping matches. Deterministic."""
    words = _WORDS.findall(text)
    found: dict[str, Concept] = {}
    i = 0
    while i < len(words):
        for n in range(min(NGRAM_MAX, len(words) - i), 0, -1):
            concept = graph.lookup(" ".join(words[i : i + n]))
            if concept is not None:
                found.setdefault(concept.id, concept)
                i += n
                break
        else:
            i += 1
    return tuple(found.values())


def is_relevant(result: WebResult, topic: str, concepts: Iterable[Concept]) -> bool:
    """The item names its topic, or at least one concept of that domain (§A.2): sports news
    rarely says "sport", but it does name offside or a penalty."""
    label = BY_ID[topic].label.casefold()
    text = f"{result.title} {result.snippet}".casefold()
    stem = label[:-1] if label.endswith("s") else label
    if re.search(rf"\b{re.escape(stem)}", text):
        return True
    return any(c.domain == topic for c in concepts)


def published(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        when = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            when = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
    return when if when.tzinfo else when.replace(tzinfo=UTC)


def recent_enough(result: WebResult, now: datetime) -> bool:
    """Articles published within 14 days when a date is given (applied when fetching or
    seeding, never when serving a demo snapshot)."""
    if result.format != "article":
        return True
    when = published(result.published_at)
    return when is None or now - when <= ARTICLE_MAX_AGE


def readiness(new_count: int) -> float:
    if new_count == 0:
        return NOTHING_NEW
    if new_count <= READY_MAX:
        return 1.0
    return TOO_MUCH_DECAY ** (new_count - READY_MAX)


def is_new(concept: Concept, reader: ReaderState, now: datetime) -> bool:
    """New to this reader: band "unaware" or "heard of" (p_know < 0.5)."""
    p0 = model.prior(reader.theta.get(concept.domain, 0.0), concept.base_difficulty)
    edge = reader.edges.get(concept.id)
    p = model.current_p_know(edge, p0, now) if edge is not None else p0
    return p < 0.5


def why(topic: str, new: Sequence[str], goal: str | None) -> str:
    parts = [BY_ID[topic].label]
    if new:
        parts.append(f"{len(new)} idea{'s' if len(new) != 1 else ''} new to you")
    if goal:
        parts.append(f"helps your goal: {goal}")
    return " · ".join(parts)


def rank(
    candidates: Sequence[FeedCandidate], reader: FeedReader, now: datetime
) -> list[RankedItem]:
    top = max((reader.interest.get(c.topic, 0.0) for c in candidates), default=0.0) or 1.0
    out = []
    for c in candidates:
        new = tuple(x.label for x in c.concepts if is_new(x, reader.state, now))
        goal = next((reader.goal_targets[x.id] for x in c.concepts if x.id in reader.goal_targets),
                    None)  # fmt: skip
        interest = (reader.interest.get(c.topic, 0.0) or top) / top
        affinity = format_affinity(
            c.result.format, reader.prior, reader.stats.get(c.result.format, FormatStats()),
            duration_s=c.result.duration_or_read_time,
        )  # fmt: skip
        score = (
            interest
            * affinity
            * readiness(len(new))
            * (GOAL_BOOST if goal else 1.0)
            * freshness(c.result.published_at, now)
        )
        out.append(RankedItem(c, round(score, 4), new, goal, why(c.topic, new, goal)))
    return out


def select(ranked: Sequence[RankedItem], topics: Sequence[str]) -> list[RankedItem]:
    """Per topic: up to 3 articles, 2 videos, 1 podcast (best first, one per URL); then the
    topics' picks interleaved by score, at most 24."""
    seen: set[str] = set()
    per_topic: list[list[RankedItem]] = []
    for topic in topics:
        picked: list[RankedItem] = []
        for fmt, quota in QUOTAS.items():
            pool = sorted(
                (
                    r
                    for r in ranked
                    if r.candidate.topic == topic and r.candidate.result.format == fmt
                ),
                key=lambda r: (-r.score, r.candidate.result.url),
            )
            for r in pool:
                if len([p for p in picked if p.candidate.result.format == fmt]) >= quota:
                    break
                if r.candidate.result.url not in seen:
                    seen.add(r.candidate.result.url)
                    picked.append(r)
        per_topic.append(sorted(picked, key=lambda r: -r.score))
    out: list[RankedItem] = []
    for rank_i in range(max((len(p) for p in per_topic), default=0)):
        layer = [p[rank_i] for p in per_topic if rank_i < len(p)]
        out.extend(sorted(layer, key=lambda r: -r.score))
    return out[:MAX_ITEMS]
