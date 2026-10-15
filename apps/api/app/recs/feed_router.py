"""GET /v1/feed — the For you feed (M7.5 §A, decision 50, DESIGN §17). No LLM on this path."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.config import get_settings
from app.content import catalog
from app.context import ReaderContext, reader_context
from app.graph.loader import get_graph
from app.graph.taxonomy import BY_ID
from app.ingest.models import ContentDoc
from app.media.openable import open_here
from app.recs import feed_rank as fr
from app.recs.feed import (
    PERSONA_COUNTRY,
    PERSONA_TOPICS,
    FeedSearch,
    SnapshotRepo,
    item_id,
    now_utc,
    offered,
    outlet_candidates,
    reader_topics,
    side_for,
    snapshot_candidates,
    thin_topics,
)
from app.recs.models import Format
from app.recs.outlets import LOCAL_SHARE
from app.recs.rank import PERSONA_FORMAT_PRIORS
from app.recs.state import Served, get_rec_signals
from app.recs.web_search import get_web_search
from app.store.docstore import get_doc_store
from app.store.outlet_repo import OutletStore

log = logging.getLogger("app.recs.feed")
router = APIRouter()


class FeedItemOut(BaseModel):
    id: str
    topic: str
    topic_label: str
    format: Format
    title: str
    url: str
    source: str
    snippet: str
    thumbnail: str | None
    duration_or_read_time: int | None
    published_at: str | None
    new_concepts: list[str]
    goal: str | None
    why: str
    score: float
    # From the reader's own map (decision 60): None when the item names no graph concept.
    readiness: fr.Readiness | None = None
    read_first: list[str] = []
    # "article": readiness from the stored article's key ideas (decision 65); else the title.
    readiness_basis: fr.ReadinessBasis = "title"
    # Opens in Gloss (articles; videos within the media caps) or only at the source.
    open_here: bool = True


class FeedResponse(BaseModel):
    topics: list[str]
    items: list[FeedItemOut]
    pending: bool  # searches still running: ask again shortly
    snapshot: bool  # a demo persona's pre-seeded picks (decision 38)
    prepared_at: str | None  # when the snapshot was made
    country: str | None  # the signed-in reader's chosen country (None: not set, or a demo)


_search: FeedSearch | None = None


def get_feed_search() -> FeedSearch:
    global _search
    if _search is None:
        _search = FeedSearch(get_web_search())
    return _search


def set_feed_search(search: FeedSearch | None) -> None:
    global _search
    _search = search


async def goal_targets(ctx: ReaderContext) -> dict[str, str]:
    """Learning-goal target concept id → the goal's label (signed-in readers; §C)."""
    if ctx.caller.is_anonymous:
        return {}
    from app.me.goals import targets_for_feed

    return await targets_for_feed(ctx.uid)


@router.get("/feed", response_model=FeedResponse)
async def get_feed(ctx: Annotated[ReaderContext, Depends(reader_context)]) -> FeedResponse:
    graph, now = get_graph(), now_utc()
    if ctx.caller.is_anonymous:
        persona = ctx.persona or "newcomer"
        snap = await SnapshotRepo(get_doc_store()).get(persona)
        topics = list(snap.topics if snap else PERSONA_TOPICS[persona])
        candidates = snapshot_candidates(snap, graph) if snap else []
        interest = dict.fromkeys(topics, 1.0)
        pending, prepared_at = False, snap.prepared_at if snap else None
        country: str | None = PERSONA_COUNTRY
    else:
        interest = {d: s.interest for d, s in ctx.domains.items()}
        topics = reader_topics(interest)
        country = ctx.user.country
        lists = await OutletStore(get_doc_store()).read(topics)
        by_topic = outlet_candidates(lists, country, graph, now)
        # Only topics short of outlet articles search (restricted to top outlets); videos and
        # podcasts as before.
        gathered = await get_feed_search().gather(
            topics, graph, now, article_topics=thin_topics(by_topic, topics)
        )
        candidates = [c for cs in by_topic.values() for c in cs]
        candidates += offered(gathered.candidates, country)
        pending, prepared_at = gathered.pending, None
    signals = await get_rec_signals().signals(ctx.uid, ctx.rec_key)
    # "Not interested" (and finished items) stay gone for this reader.
    gone = ("dismissed", "completed")
    candidates = [c for c in candidates if signals.seen.get(item_id(c.result.url)) not in gone]
    candidates = fr.attach_ideas(candidates, await _library(), graph)
    reader = fr.FeedReader(
        state=ctx.state,
        interest=interest,
        prior=PERSONA_FORMAT_PRIORS[ctx.rec_key],
        stats=signals.formats,
        goal_targets=await goal_targets(ctx),
    )
    side = side_for(country)
    ranked = fr.select(fr.rank(candidates, reader, now, graph), topics, side, LOCAL_SHARE)
    _log_mix(ranked, side, country)
    settings, anonymous = get_settings(), ctx.caller.is_anonymous
    items = [
        i.model_copy(update={"open_here": await open_here(
            i.url, i.format, i.duration_or_read_time, settings, anonymous
        )})
        for i in (_out(r) for r in ranked)
    ]  # fmt: skip
    if items and ctx.user.may_record:  # signed-in readers: nothing recorded before consent
        await get_rec_signals().remember_served(
            ctx.uid, ctx.rec_key, {i.id: Served(i.format, "feed") for i in items}, now
        )
    return FeedResponse(
        topics=topics,
        items=items,
        pending=pending,
        snapshot=ctx.caller.is_anonymous,
        prepared_at=prepared_at,
        country=None if ctx.caller.is_anonymous else ctx.user.country,
    )


def _log_mix(ranked: list[fr.RankedItem], side: fr.SideOf, country: str | None) -> None:
    """Counts only (decision 50 §C): local/global articles served and the 60% target."""
    sides = [side(r.candidate) for r in ranked if r.candidate.result.format == "article"]
    local = sides.count("local")
    log.info(
        "feed mix",
        extra={
            "country_set": country is not None,
            "articles": len(sides),
            "local": local,
            "global": len(sides) - local,
            "local_target": int(LOCAL_SHARE * len(sides) + 0.5) if country else 0,
        },
    )


async def _library() -> dict[str, ContentDoc]:
    """Stored docs by id for decision 65's readiness. The catalog loads once per process (a cold
    instance streams the contents collection here); if that fails the feed keeps the title rule."""
    try:
        return {d.content_id: d for d in await catalog.all_docs()}
    except Exception:
        log.exception("feed library unavailable; readiness from titles")
        return {}


def _out(r: fr.RankedItem) -> FeedItemOut:
    res, topic = r.candidate.result, r.candidate.topic
    return FeedItemOut(
        id=item_id(res.url),
        topic=topic,
        topic_label=BY_ID[topic].label,
        format=res.format,
        title=res.title,
        url=res.url,
        source=res.source,
        snippet=res.snippet,
        thumbnail=res.thumbnail,
        duration_or_read_time=res.duration_or_read_time,
        published_at=res.published_at,
        new_concepts=list(r.new_concepts),
        goal=r.goal_label,
        why=r.why,
        score=r.score,
        readiness=r.readiness,
        read_first=list(r.read_first),
        readiness_basis=r.readiness_basis,
    )
