"""For you feed (M7.5 §A, decision 50, DESIGN §17): topics, outlet articles, shared
day-keyed searches, demo snapshots.

A signed-in reader's topics are their strongest stored interests (taxonomy domains); a demo
persona has a fixed pair and is served a pre-seeded snapshot (decision 38). Articles come from
top outlets' section feeds, collected twice a day (`outlet_job`); a topic with fewer than
OUTLET_MIN offered outlet articles falls back to one article search restricted to the registry's
outlets and two wires (`feedx:` keys, so the old unrestricted `feed:` article entries are never
served again). Videos and podcasts are searched as before. Search queries are only a taxonomy
or concept label plus a fixed phrase, never reader text, history or country. Each (key, format,
UTC day) is searched at most once for everyone and cached in `rec_cache`. Missing searches run
inside the request with a time limit (Cloud Run throttles CPU after a response); what doesn't
finish in time is `pending` and joins the in-flight task on the next ask. No LLM anywhere.
"""

import asyncio
import hashlib
import logging
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from app.graph.graph import ConceptGraph
from app.graph.models import Concept
from app.graph.taxonomy import BUSINESS_DOMAINS, BY_ID, DOMAIN_IDS
from app.recs import feed_rank as fr
from app.recs.models import FORMATS, Format, WebResult
from app.recs.outlets import BY_OUTLET, eligible, fallback_domains, side_of
from app.recs.web_search import WebSearch, host_of, mentions
from app.store.docstore import DocStore
from app.store.outlet_repo import OutletList
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
# Demo personas read as India (decision 51): their snapshots mix 60% Indian outlets + 40% global.
PERSONA_COUNTRY = "IN"
SNAPSHOTS = "persona_feeds"
OUTLET_MIN = 3  # offered outlet articles a topic needs before the search fallback is skipped
STALE_RUN = timedelta(hours=36)  # newest collection older than this is logged
log = logging.getLogger("app.recs.feed")


def feed_query(domain: str, fmt: Format) -> str:
    """The whole outgoing query: the taxonomy label and a fixed phrase. Nothing else."""
    return f"{BY_ID[domain].label} {FEED_PHRASE[fmt]}"


def feed_key(domain: str, day: str) -> str:
    """Video and podcast entries (unchanged since M7.5)."""
    return f"feed:{domain}:{day}"


def fallback_key(domain: str, day: str) -> str:
    """The restricted article fallback (decision 50)."""
    return f"feedx:{domain}:{day}"


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
    return f"feedx:c:{concept_id}:{day}"


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
    include_domains: tuple[str, ...] = ()

    def key(self, day: str) -> str:
        return f"{self.stem}:{day}"


FALLBACK_DOMAINS: tuple[str, ...] = tuple(fallback_domains())


def topic_specs(
    topics: Sequence[str], formats: Iterable[Format], graph: ConceptGraph, now: datetime,
    article_topics: Sequence[str] = (),
) -> list[SearchSpec]:  # fmt: skip
    """Videos and podcasts for every topic (`feed:` stems); articles only for `article_topics`
    (the thin ones), restricted to FALLBACK_DOMAINS under `feedx:` stems."""
    specs = []
    for t in topics:
        for fmt in FORMATS:
            if fmt not in formats:
                continue
            if fmt != "article":
                specs.append(SearchSpec(f"feed:{t}", t, fmt, feed_query(t, fmt),
                                        keep_for(t, graph, now)))  # fmt: skip
            elif t in article_topics:
                specs.append(SearchSpec(f"feedx:{t}", t, fmt, feed_query(t, fmt),
                                        keep_for(t, graph, now),
                                        include_domains=FALLBACK_DOMAINS))  # fmt: skip
    return specs


def concept_spec(concept: Concept, now: datetime, sub_cap: tuple[str, int]) -> SearchSpec:
    """Articles only (decision 41): one search per concept per day, shared by everyone,
    restricted to FALLBACK_DOMAINS (decision 50)."""
    return SearchSpec(f"feedx:c:{concept.id}", concept.domain, "article", concept_query(concept),
                      keep_for_concept(concept, now), sub_cap,
                      include_domains=FALLBACK_DOMAINS)  # fmt: skip


# ---------------------------------------------------------------- outlet articles (decision 50)


def outlet_candidates(
    lists: Mapping[str, Sequence[OutletList]], country: str | None, graph: ConceptGraph,
    now: datetime | None = None,
) -> dict[str, list[fr.FeedCandidate]]:  # fmt: skip
    """topic → candidates from the outlets this reader is offered (their country's own as local,
    other global outlets as global). The section is the topic, so no topic-word filter; concepts
    are still named for readiness. A newest collection older than STALE_RUN is logged."""
    out: dict[str, list[fr.FeedCandidate]] = {}
    newest = ""
    for topic, entries in lists.items():
        group: list[fr.FeedCandidate] = []
        for entry in entries:
            newest = max(newest, entry.fetched_at)
            outlet = BY_OUTLET.get(entry.outlet_id)
            if outlet is None or eligible(outlet, country) is None:
                continue
            group += _candidates(topic, entry.items, graph)
        out[topic] = group
    if now is not None and newest and now - datetime.fromisoformat(newest) > STALE_RUN:
        log.warning("outlet entries stale", extra={"newest_run": newest})
    return out


def thin_topics(by_topic: Mapping[str, Sequence[fr.FeedCandidate]], topics: Sequence[str]):
    """Topics with fewer than OUTLET_MIN offered outlet articles (they get the fallback)."""
    return [t for t in topics if len(by_topic.get(t, ())) < OUTLET_MIN]


def side_for(country: str | None) -> fr.SideOf:
    """A candidate's side for this reader, by its URL's host (None: not offered)."""

    def side(c: fr.FeedCandidate) -> str | None:
        return side_of(host_of(c.result.url), country)

    return side


def offered(candidates: Iterable[fr.FeedCandidate], country: str | None) -> list[fr.FeedCandidate]:
    """Fallback articles from outlets this reader isn't offered are dropped (the search itself
    is the same for everyone); videos and podcasts pass."""
    side = side_for(country)
    return [c for c in candidates if c.result.format != "article" or side(c) is not None]


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
        wait_s: float = FETCH_WAIT_S, article_topics: Sequence[str] = (),
    ) -> Gathered:  # fmt: skip
        specs = topic_specs(topics, self._web.formats, graph, now, article_topics)
        return await self.gather_specs(specs, graph, now, wait_s)

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
                    self._web.fetch_feed(key, spec.fmt, spec.query, spec.keep, spec.sub_cap,
                                         include_domains=spec.include_domains)
                )  # fmt: skip
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
