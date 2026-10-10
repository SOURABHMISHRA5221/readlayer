"""GET /v1/feed — the For you feed (M7.5 §A, DESIGN §17). No LLM on this path."""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.context import ReaderContext, reader_context
from app.graph.loader import get_graph
from app.graph.taxonomy import BY_ID
from app.recs import feed_rank as fr
from app.recs.feed import (
    PERSONA_TOPICS,
    FeedSearch,
    SnapshotRepo,
    item_id,
    now_utc,
    reader_topics,
    snapshot_candidates,
)
from app.recs.models import Format
from app.recs.rank import PERSONA_FORMAT_PRIORS
from app.recs.state import Served, get_rec_signals
from app.recs.web_search import get_web_search
from app.store.docstore import get_doc_store

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


class FeedResponse(BaseModel):
    topics: list[str]
    items: list[FeedItemOut]
    pending: bool  # searches still running: ask again shortly
    snapshot: bool  # a demo persona's pre-seeded picks (decision 38)
    prepared_at: str | None  # when the snapshot was made


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
    else:
        interest = {d: s.interest for d, s in ctx.domains.items()}
        topics = reader_topics(interest)
        gathered = await get_feed_search().gather(topics, graph, now)
        candidates, pending, prepared_at = gathered.candidates, gathered.pending, None
    signals = await get_rec_signals().signals(ctx.uid, ctx.rec_key)
    # "Not interested" (and finished items) stay gone for this reader.
    gone = ("dismissed", "completed")
    candidates = [c for c in candidates if signals.seen.get(item_id(c.result.url)) not in gone]
    reader = fr.FeedReader(
        state=ctx.state,
        interest=interest,
        prior=PERSONA_FORMAT_PRIORS[ctx.rec_key],
        stats=signals.formats,
        goal_targets=await goal_targets(ctx),
    )
    ranked = fr.select(fr.rank(candidates, reader, now), topics)
    items = [_out(r) for r in ranked]
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
    )


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
    )
