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
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

from app.graph.graph import ConceptGraph
from app.graph.models import Concept
from app.graph.taxonomy import BY_ID
from app.reader import model
from app.reader.state import ReaderState
from app.recs.models import PODCAST_DOMAINS, Format, WebResult
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
# Path segments of section, tag and listing pages ("latest news" searches return many of them).
HUB_SEGMENTS = frozenset(
    {"tag", "tags", "topic", "topics", "category", "categories", "section", "sections",
     "news-event", "hub", "author", "authors", "search"}
)  # fmt: skip
# Podcast-directory pages that list many shows rather than being one show or episode.
DIRECTORY_SEGMENTS = frozenset({"charts", "chart", "genre", "genres", "browse", "search", "top",
                                "category", "categories"})  # fmt: skip
SLUG_MIN_WORDS = 3
_ID_DIGITS = re.compile(r"\d{4,}")


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


_SCOPE_STOP = frozenset({"and", "the", "their", "its", "of", "for", "power", "rules"})
SHORT_STEM = 4  # "tech", "econ", "educ": long labels also match their short forms
LONG_LABEL = 7


def topic_pattern(topic: str) -> re.Pattern[str]:
    """Words that say an item is about the topic: the label's stem (and, for labels of 7+
    letters, its first 4 letters), plus the words of the domain's one-line scope in the
    taxonomy ("AI", "software", "inflation"). Deterministic, no new keyword list."""
    info = BY_ID[topic]
    label = info.label.casefold()
    stems = {label[:-1] if label.endswith("s") else label}
    if len(label) >= LONG_LABEL:
        stems.add(label[:SHORT_STEM])
    scope = {w for w in re.findall(r"[a-z]{3,}|[A-Z]{2,}", info.scope)
             if w.casefold() not in _SCOPE_STOP}  # fmt: skip
    prefixes = "|".join(sorted(re.escape(s) for s in stems))
    words = "|".join(sorted(re.escape(w.casefold()) for w in scope))
    return re.compile(rf"\b(?:{prefixes})|\b(?:{words})\b")


def is_relevant(result: WebResult, topic: str, concepts: Iterable[Concept]) -> bool:
    """The item names its topic (label, short form or a scope word), or at least one concept
    of that domain (§A.2): sports news rarely says "sport", but it does name a penalty."""
    text = f"{result.title} {result.snippet}".casefold()
    if topic_pattern(topic).search(text):
        return True
    return any(c.domain == topic for c in concepts)


def _segments(url: str) -> list[str]:
    return [s for s in urlsplit(url).path.casefold().split("/") if s]


def looks_like_article(url: str) -> bool:
    """One article, not a section, tag or home page: no hub segment, and the last path segment
    is a slug of ≥ 3 words or the path carries a date or numeric id. Deterministic; a short
    real slug is the accepted loss."""
    segments = _segments(url)
    if not segments or HUB_SEGMENTS.intersection(segments):
        return False
    last = re.sub(r"\.(s?html?|php|aspx?)$", "", segments[-1])
    return len(re.split(r"[-_]+", last)) >= SLUG_MIN_WORDS or bool(
        _ID_DIGITS.search("/".join(segments))
    )


def is_listing_page(url: str, directories: Iterable[str] = ()) -> bool:
    """A podcast directory's chart, genre or browse page, or its home page (many shows, not
    one). A show hosted on its own subdomain (name.podbean.com) is not a listing."""
    segments = _segments(url)
    host = (urlsplit(url).hostname or "").removeprefix("www.")
    return bool(DIRECTORY_SEGMENTS.intersection(segments)) or (not segments and host in directories)


LATIN_SHARE = 0.7


def mostly_latin(text: str) -> bool:
    """At least 70% of the letters are Latin script: the explanations and the reader are in
    English, and YouTube's relevanceLanguage is only a hint."""
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return True
    return sum(ch.isascii() or "\u00c0" <= ch <= "\u024f" for ch in letters) >= LATIN_SHARE * len(
        letters
    )


def is_feed_page(result: WebResult) -> bool:
    if not mostly_latin(result.title):
        return False
    if result.format == "article":
        return looks_like_article(result.url)
    if result.format == "podcast":
        return not is_listing_page(result.url, PODCAST_DOMAINS)
    return True


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


SideOf = Callable[[FeedCandidate], str | None]  # "local" | "global" | None (not offered)


def article_split(
    pools: Sequence[tuple[int, int]], quota: int, share: float
) -> list[tuple[int, int]]:
    """Decision 50's mix. Per topic (local available, global available) → (local, global)
    article picks: each topic fills min(quota, supply) slots; over all slots the local count is
    round(share × slots) when supply allows, a short side backfilled from the other. Locals are
    handed out round-robin in topic order. Pure."""
    slots = [min(quota, loc + glo) for loc, glo in pools]
    lo = [max(0, s - glo) for s, (_, glo) in zip(slots, pools, strict=True)]
    hi = [min(loc, s) for s, (loc, _) in zip(slots, pools, strict=True)]
    target = min(max(int(share * sum(slots) + 0.5), sum(lo)), sum(hi))
    local, extra = list(lo), target - sum(lo)
    while extra > 0:
        for i in range(len(pools)):
            if extra > 0 and local[i] < hi[i]:
                local[i] += 1
                extra -= 1
    return [(n, s - n) for n, s in zip(local, slots, strict=True)]


def _best(pool: Iterable[RankedItem]) -> list[RankedItem]:
    return sorted(pool, key=lambda r: (-r.score, r.candidate.result.url))


def select(
    ranked: Sequence[RankedItem], topics: Sequence[str], side: SideOf | None = None,
    share: float = 0.6,
) -> list[RankedItem]:  # fmt: skip
    """Per topic: up to 3 articles, 2 videos, 1 podcast (best first, one per URL; a URL filed
    under two topics belongs to the earlier one); then the topics' picks interleaved by score,
    at most 24. With `side`, articles are mixed local/global per `article_split` (articles not
    offered to this reader are dropped); videos and podcasts are outside the mix."""
    seen: set[str] = set()
    pools: list[dict[str, list[RankedItem]]] = []
    for topic in topics:
        by_kind: dict[str, list[RankedItem]] = {}
        for r in _best(r for r in ranked if r.candidate.topic == topic):
            url, fmt = r.candidate.result.url, r.candidate.result.format
            if url in seen:
                continue
            kind: str = fmt
            if fmt == "article" and side is not None:
                where = side(r.candidate)
                if where is None:
                    continue
                kind = f"article:{where}"
            seen.add(url)
            by_kind.setdefault(kind, []).append(r)
        pools.append(by_kind)
    split = article_split(
        [(len(p.get("article:local", [])), len(p.get("article:global", []))) for p in pools],
        QUOTAS["article"],
        share,
    )
    per_topic: list[list[RankedItem]] = []
    for p, (n_local, n_global) in zip(pools, split, strict=True):
        picked = (
            p.get("article", [])[: QUOTAS["article"]]
            + p.get("article:local", [])[:n_local]
            + p.get("article:global", [])[:n_global]
        )
        for fmt in ("video", "podcast"):
            picked += p.get(fmt, [])[: QUOTAS[fmt]]
        per_topic.append(_best(picked))
    out: list[RankedItem] = []
    for rank_i in range(max((len(p) for p in per_topic), default=0)):
        layer = [p[rank_i] for p in per_topic if rank_i < len(p)]
        out.extend(sorted(layer, key=lambda r: -r.score))
    return out[:MAX_ITEMS]


def onboarding_mix(
    groups: Sequence[Sequence[FeedCandidate]], now: datetime, limit: int
) -> list[FeedCandidate]:
    """Onboarding's screen 2 (decision 41): one group per chosen topic or concept, in the
    reader's order. Within a group articles first, then fresher first (ties by URL); the groups
    are interleaved so every one with results gets a card before any gets a second. One per URL.
    """
    ordered = [
        sorted(g, key=lambda c: (c.result.format != "article",
                                 -freshness(c.result.published_at, now), c.result.url))
        for g in groups
    ]  # fmt: skip
    out: list[FeedCandidate] = []
    seen: set[str] = set()
    for layer in range(max((len(g) for g in ordered), default=0)):
        for g in ordered:
            if layer < len(g) and g[layer].result.url not in seen and len(out) < limit:
                seen.add(g[layer].result.url)
                out.append(g[layer])
    return out
