"""For you feed (M7.5 §A, DESIGN §17): topics, shared day-keyed searches, demo snapshots.

A signed-in reader's topics are their strongest stored interests (taxonomy domains); a demo
persona has a fixed pair and is served a pre-seeded snapshot (decision 38). Search queries are
only a taxonomy label plus a fixed phrase, never reader text or history. Each (topic, format,
UTC day) is searched at most once for everyone and cached in `rec_cache`. Missing searches run
inside the request with a time limit (Cloud Run throttles CPU after a response); what doesn't
finish in time is `pending` and joins the in-flight task on the next ask. No LLM anywhere.
"""

import asyncio
import hashlib
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from app.graph.graph import ConceptGraph
from app.graph.models import Concept
from app.graph.taxonomy import BUSINESS_DOMAINS, BY_ID, DOMAIN_IDS
from app.recs import feed_rank as fr
from app.recs.models import FORMATS, Format, WebResult
from app.recs.web_search import WebSearch, mentions
from app.store.docstore import DocStore
from app.store.spend_repo import today_utc

MAX_TOPICS = 6
MIN_TOPIC_INTEREST = 0.5  # onboarding stores 1.0 for chosen domains and 0.3 for the rest
EMPTY_RETRY = timedelta(hours=1)  # an empty day entry may be searched again (within the caps)
MAX_SEARCHES = 2  # per instance (≤ 3) and (topic, format, day): ≤ 6 in all, inside the feed cap
FAILURE_BACKOFF = timedelta(minutes=10)  # after a cap hit or provider failure
FETCH_WAIT_S = 6.0
FEED_PHRASE: Mapping[Format, str] = {
    # "latest news" returned section and tag pages; plain "news" swung between 2 and 10 real
    # articles out of 15; "news this week" gave 8–15 on every sample (2026-10-10).
    # "podcast episode" returned nothing for some topics (Economics); "podcast" returns shows.
    # Videos: news explainers, medium length, last 30 days (YouTubeProvider).
    "article": "news this week",
    "podcast": "podcast",
    "video": "news explained",
}
PERSONA_TOPICS: Mapping[str, tuple[str, str]] = {
    "newcomer": ("technology", "economics"),  # a software engineer meeting economics
    "trader": ("finance", "business"),
    "policy_student": ("policy", "politics"),
}
SNAPSHOTS = "persona_feeds"


def feed_query(domain: str, fmt: Format) -> str:
    """The whole outgoing query: the taxonomy label and a fixed phrase. Nothing else."""
    return f"{BY_ID[domain].label} {FEED_PHRASE[fmt]}"


def feed_key(domain: str, day: str) -> str:
    return f"feed:{domain}:{day}"


def item_id(url: str) -> str:
    return "feed:" + hashlib.sha1(url.encode()).hexdigest()[:16]


def reader_topics(interest: Mapping[str, float]) -> list[str]:
    """Up to MAX_TOPICS taxonomy domains the reader chose or raised (interest ≥ 0.5), strongest
    first (ties in taxonomy order); none that strong → their strongest stored domains; none
    stored → the four business domains."""
    ranked = sorted(
        (d for d in DOMAIN_IDS if interest.get(d, 0.0) > 0),
        key=lambda d: (-interest[d], DOMAIN_IDS.index(d)),
    )
    chosen = [d for d in ranked if interest[d] >= MIN_TOPIC_INTEREST]
    return (chosen or ranked)[:MAX_TOPICS] or list(BUSINESS_DOMAINS)


def keep_for(topic: str, graph: ConceptGraph, now: datetime):
    def keep(r: WebResult) -> bool:
        concepts = fr.named_concepts(graph, f"{r.title} {r.snippet}")
        return (
            fr.is_feed_page(r) and fr.recent_enough(r, now) and fr.is_relevant(r, topic, concepts)
        )

    return keep


def concept_key(concept_id: str, day: str) -> str:
    return f"feed:c:{concept_id}:{day}"


def concept_query(concept: Concept) -> str:
    """Onboarding (decision 41): a resolved concept's graph label and the article phrase."""
    return f"{concept.label} {FEED_PHRASE['article']}"


def keep_for_concept(concept: Concept, now: datetime):
    """Concept results must name the concept (label or an alias), not just its domain."""
    names = [concept.label, *concept.aliases]

    def keep(r: WebResult) -> bool:
        text = f"{r.title} {r.snippet}"
        return (
            fr.is_feed_page(r)
            and fr.recent_enough(r, now)
            and any(mentions(n, text) for n in names)
        )

    return keep


@dataclass(frozen=True)
class SearchSpec:
    """One shared day-keyed search: the cache key's stem (`feed:<topic>` or
    `feed:c:<concept>`; the UTC day is appended), the domain its results are filed under, the
    whole outgoing query, the keep filter and an optional shared sub-cap (counter, limit)."""

    stem: str
    topic: str
    fmt: Format
    query: str
    keep: Callable[[WebResult], bool]
    sub_cap: tuple[str, int] | None = None

    def key(self, day: str) -> str:
        return f"{self.stem}:{day}"


def topic_specs(
    topics: Sequence[str], formats: Iterable[Format], graph: ConceptGraph, now: datetime
) -> list[SearchSpec]:
    return [
        SearchSpec(f"feed:{t}", t, fmt, feed_query(t, fmt), keep_for(t, graph, now))
        for t in topics
        for fmt in FORMATS
        if fmt in formats
    ]


def concept_spec(concept: Concept, now: datetime, sub_cap: tuple[str, int]) -> SearchSpec:
    """Articles only (decision 41): one search per concept per day, shared by everyone."""
    return SearchSpec(f"feed:c:{concept.id}", concept.domain, "article", concept_query(concept),
                      keep_for_concept(concept, now), sub_cap)  # fmt: skip


@dataclass
class Gathered:
    candidates: list[fr.FeedCandidate]
    pending: bool
    by_stem: dict[str, list[fr.FeedCandidate]] = field(default_factory=dict)


# Asked once, before the first search a gather would start; False = start none (serve cached
# entries and yesterday's instead). Onboarding counts a reader's discover calls with it.
MayStart = Callable[[], Awaitable[bool]]


class FeedSearch:
    """Shared, day-keyed searches for the For you feed, with in-flight de-duplication.

    Per (key, format, UTC day) and instance, at most MAX_SEARCHES searches: the first, and one
    more an hour later if it came back empty (or after a failure, FAILURE_BACKOFF later). When a
    search can't run (a cap, a failure, the limit) and today has no entry, yesterday's entry is
    served if there is one. Topic keys and onboarding's concept keys share all of this."""

    def __init__(self, web: WebSearch) -> None:
        self._web = web
        self._inflight: dict[tuple[str, Format], asyncio.Task[list[WebResult] | None]] = {}
        self._searches: dict[tuple[str, Format], int] = {}
        self._failed_at: dict[tuple[str, Format], datetime] = {}

    @property
    def formats(self) -> frozenset[Format]:
        return self._web.formats

    def _prune(self, day: str) -> None:
        for store in (self._inflight, self._searches, self._failed_at):
            for k in [k for k in store if not k[0].endswith(day)]:
                del store[k]

    def _may_search(self, k: tuple[str, Format], now: datetime) -> bool:
        failed = self._failed_at.get(k)
        if failed is not None and now - failed < FAILURE_BACKOFF:
            return False
        return self._searches.get(k, 0) < MAX_SEARCHES

    async def gather(
        self, topics: Sequence[str], graph: ConceptGraph, now: datetime,
        wait_s: float = FETCH_WAIT_S,
    ) -> Gathered:  # fmt: skip
        return await self.gather_specs(
            topic_specs(topics, self._web.formats, graph, now), graph, now, wait_s
        )

    async def gather_specs(
        self, specs: Sequence[SearchSpec], graph: ConceptGraph, now: datetime,
        wait_s: float = FETCH_WAIT_S, may_start: MayStart | None = None,
    ) -> Gathered:  # fmt: skip
        day = today_utc()
        self._prune(day)
        found: dict[SearchSpec, list[WebResult]] = {}
        tasks: dict[SearchSpec, asyncio.Task[list[WebResult] | None]] = {}
        allowed: bool | None = None if may_start is not None else True
        for spec in specs:
            if spec.fmt not in self._web.formats:
                continue
            key = spec.key(day)
            k = (key, spec.fmt)
            entry = await self._web.cached_entry(key, spec.fmt, spec.query)
            fresh = entry is not None and (entry.results or now - entry.fetched_at < EMPTY_RETRY)
            task = self._inflight.get(k)
            if entry is not None and (fresh or not self._may_search(k, now)):
                found[spec] = entry.results
                continue
            if task is None or task.done():
                if allowed is None:
                    allowed = await may_start()  # type: ignore[misc]
                if not allowed or not self._may_search(k, now):
                    found[spec] = entry.results if entry else await self._yesterday(spec)
                    continue
                self._searches[k] = self._searches.get(k, 0) + 1
                task = asyncio.create_task(
                    self._web.fetch_feed(key, spec.fmt, spec.query, spec.keep, spec.sub_cap)
                )
                self._inflight[k] = task
            tasks[spec] = task
        if tasks:
            await asyncio.wait(tasks.values(), timeout=wait_s)
        pending = False
        for spec, task in tasks.items():
            if not task.done():
                pending = True
                continue
            result = None if task.cancelled() or task.exception() else task.result()
            if result is None:  # a cap or a provider failure: no search for a while
                self._failed_at[(spec.key(day), spec.fmt)] = now
                result = await self._yesterday(spec)
            found[spec] = result
        by_stem: dict[str, list[fr.FeedCandidate]] = {}
        for spec, results in found.items():
            by_stem.setdefault(spec.stem, []).extend(_candidates(spec.topic, results, graph))
        return Gathered([c for cs in by_stem.values() for c in cs], pending, by_stem)

    async def _yesterday(self, spec: SearchSpec) -> list[WebResult]:
        day = (datetime.fromisoformat(today_utc()) - timedelta(days=1)).date().isoformat()
        entry = await self._web.cached_entry(spec.key(day), spec.fmt, spec.query)
        return entry.results if entry is not None else []


def _candidates(
    topic: str, results: Sequence[WebResult], graph: ConceptGraph
) -> list[fr.FeedCandidate]:
    return [
        fr.FeedCandidate(r, topic, fr.named_concepts(graph, f"{r.title} {r.snippet}"))
        for r in results
    ]


# ---------------------------------------------------------------- demo snapshots (decision 38)


@dataclass(frozen=True)
class Snapshot:
    persona: str
    prepared_at: str
    topics: tuple[str, ...]
    items: tuple[tuple[str, WebResult], ...]  # (topic, result)


class SnapshotRepo:
    def __init__(self, store: DocStore) -> None:
        self._store = store

    async def get(self, persona: str) -> Snapshot | None:
        doc = await self._store.get(f"{SNAPSHOTS}/{persona}")
        if not doc:
            return None
        return Snapshot(
            persona,
            doc["prepared_at"],
            tuple(doc.get("topics", [])),
            tuple(
                (i["topic"], WebResult.model_validate(i["result"])) for i in doc.get("items", [])
            ),
        )

    async def put(self, snap: Snapshot) -> None:
        doc: dict[str, Any] = {
            "prepared_at": snap.prepared_at,
            "topics": list(snap.topics),
            "items": [{"topic": t, "result": r.model_dump()} for t, r in snap.items],
        }

        async def body(t: Any) -> None:
            t.set(f"{SNAPSHOTS}/{snap.persona}", doc)

        await self._store.run(body)


def snapshot_candidates(snap: Snapshot, graph: ConceptGraph) -> list[fr.FeedCandidate]:
    """Serve-time: no date filter (judging runs for weeks after the snapshot is made)."""
    return [
        fr.FeedCandidate(r, topic, fr.named_concepts(graph, f"{r.title} {r.snippet}"))
        for topic, r in snap.items
    ]


def now_utc() -> datetime:
    return datetime.now(UTC)
