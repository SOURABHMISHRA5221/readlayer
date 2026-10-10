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
from datetime import UTC, datetime
from typing import Any

from app.graph.graph import ConceptGraph
from app.graph.taxonomy import BUSINESS_DOMAINS, BY_ID, DOMAIN_IDS
from app.recs import feed_rank as fr
from app.recs.models import FORMATS, Format, WebResult
from app.recs.web_search import WebSearch
from app.store.docstore import DocStore
from app.store.spend_repo import today_utc

MAX_TOPICS = 6
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
    """Top MAX_TOPICS taxonomy domains by stored interest (ties in taxonomy order); none
    stored → the four business domains."""
    ranked = sorted(
        (d for d in DOMAIN_IDS if interest.get(d, 0.0) > 0),
        key=lambda d: (-interest[d], DOMAIN_IDS.index(d)),
    )
    return ranked[:MAX_TOPICS] or list(BUSINESS_DOMAINS)


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
    """Shared, day-keyed searches for the For you feed, with in-flight de-duplication."""

    def __init__(self, web: WebSearch) -> None:
        self._web = web
        self._inflight: dict[tuple[str, Format], asyncio.Task[list[WebResult] | None]] = {}

    async def gather(
        self, topics: Sequence[str], graph: ConceptGraph, now: datetime,
        wait_s: float = FETCH_WAIT_S,
    ) -> Gathered:  # fmt: skip
        day = today_utc()
        found: dict[tuple[str, Format], list[WebResult]] = {}
        tasks: dict[tuple[str, Format], asyncio.Task[list[WebResult] | None]] = {}
        for topic in topics:
            key = feed_key(topic, day)
            for fmt in FORMATS:
                if fmt not in self._web.formats:
                    continue
                entry = await self._web.cached_entry(key, fmt, feed_query(topic, fmt))
                if entry is not None:
                    found[(topic, fmt)] = entry.results
                    continue
                task = self._inflight.get((key, fmt))
                if task is None or task.done():
                    task = asyncio.create_task(
                        self._web.fetch_feed(
                            key, fmt, feed_query(topic, fmt), keep_for(topic, graph, now)
                        )  # fmt: skip
                    )
                    self._inflight[(key, fmt)] = task
                tasks[(topic, fmt)] = task
        if tasks:
            await asyncio.wait(tasks.values(), timeout=wait_s)
        pending = False
        for k, task in tasks.items():
            if task.done() and not task.cancelled() and task.exception() is None:
                found[k] = task.result() or []
            else:
                pending = True
        return Gathered(_candidates(found, graph), pending)


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
