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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.graph.graph import ConceptGraph
from app.graph.taxonomy import BUSINESS_DOMAINS, BY_ID, DOMAIN_IDS
from app.recs import feed_rank as fr
from app.recs.models import FORMATS, Format, WebResult
from app.recs.web_search import WebSearch
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


@dataclass
class Gathered:
    candidates: list[fr.FeedCandidate]
    pending: bool


class FeedSearch:
    """Shared, day-keyed searches for the For you feed, with in-flight de-duplication.

    Per (topic, format, UTC day) and instance, at most MAX_SEARCHES searches: the first, and one
    more an hour later if it came back empty (or after a failure, FAILURE_BACKOFF later). When a
    search can't run (a cap, a failure, the limit) and today has no entry, yesterday's entry is
    served if there is one."""

    def __init__(self, web: WebSearch) -> None:
        self._web = web
        self._inflight: dict[tuple[str, Format], asyncio.Task[list[WebResult] | None]] = {}
        self._searches: dict[tuple[str, Format], int] = {}
        self._failed_at: dict[tuple[str, Format], datetime] = {}

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
        day = today_utc()
        self._prune(day)
        found: dict[tuple[str, Format], list[WebResult]] = {}
        tasks: dict[tuple[str, Format], asyncio.Task[list[WebResult] | None]] = {}
        for topic in topics:
            key = feed_key(topic, day)
            for fmt in FORMATS:
                if fmt not in self._web.formats:
                    continue
                k, query = (key, fmt), feed_query(topic, fmt)
                entry = await self._web.cached_entry(key, fmt, query)
                fresh = entry is not None and (
                    entry.results or now - entry.fetched_at < EMPTY_RETRY
                )
                task = self._inflight.get(k)
                if entry is not None and (fresh or not self._may_search(k, now)):
                    found[(topic, fmt)] = entry.results
                    continue
                if task is None or task.done():
                    if not self._may_search(k, now):
                        found[(topic, fmt)] = await self._yesterday(topic, fmt)
                        continue
                    self._searches[k] = self._searches.get(k, 0) + 1
                    task = asyncio.create_task(
                        self._web.fetch_feed(key, fmt, query, keep_for(topic, graph, now))
                    )
                    self._inflight[k] = task
                tasks[(topic, fmt)] = task
        if tasks:
            await asyncio.wait(tasks.values(), timeout=wait_s)
        pending = False
        for (topic, fmt), task in tasks.items():
            if not task.done():
                pending = True
                continue
            result = None if task.cancelled() or task.exception() else task.result()
            if result is None:  # a cap or a provider failure: no search for a while
                self._failed_at[(feed_key(topic, day), fmt)] = now
                result = await self._yesterday(topic, fmt)
            found[(topic, fmt)] = result
        return Gathered(_candidates(found, graph), pending)

    async def _yesterday(self, topic: str, fmt: Format) -> list[WebResult]:
        day = (datetime.fromisoformat(today_utc()) - timedelta(days=1)).date().isoformat()
        entry = await self._web.cached_entry(feed_key(topic, day), fmt, feed_query(topic, fmt))
        return entry.results if entry is not None else []


def _candidates(
    found: Mapping[tuple[str, Format], list[WebResult]], graph: ConceptGraph
) -> list[fr.FeedCandidate]:
    return [
        fr.FeedCandidate(r, topic, fr.named_concepts(graph, f"{r.title} {r.snippet}"))
        for (topic, _), results in found.items()
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
