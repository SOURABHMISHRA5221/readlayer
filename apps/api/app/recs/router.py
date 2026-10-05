"""Up next: GET recommendations, POST rec events, POST open (ingest a web article).

Triggers are the concepts this reader was shown as new (the PLACEHOLDER scorer's spans, at
balanced density); the reader graph replaces them in M4. Library items are computed on the
spot; web items come from the per-concept cache, and misses are fetched in the background
(`pending: true` tells the client to poll briefly). Anonymous (demo) readers always get cached
web results, but the uncached searches they trigger share ANON_SEARCH_DAILY_CAP; past it they
trigger none, so concepts without a cache entry give them library items only.
"""

import hashlib
import logging
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app import llm
from app.auth import Caller, current_caller
from app.config import Settings, get_settings
from app.content import catalog
from app.content.router import score_for
from app.context import ReaderContext, reader_context, scope_persona
from app.graph.graph import ConceptGraph
from app.graph.loader import get_graph
from app.ingest import quota
from app.ingest.models import ContentDoc
from app.ingest.router import (
    FETCH_ERROR_STATUS,
    MAX_URL_CHARS,
    _error,
    _ingest_error,
    ingest_url,  # lazy: loads the ingestion pipeline on first use
)
from app.ingest.safe_fetch import FetchError, validate_url
from app.ingest.urls import url_hash
from app.reader.state import PersonaKey
from app.recs.library import LibraryCandidate, LibraryIndex, is_wikipedia, library_candidates
from app.recs.models import FORMATS, Format, Relation, WebResult
from app.recs.rank import PERSONA_FORMAT_PRIORS, RELATION_LABEL, Candidate, select
from app.recs.state import DEFAULT_KEY, RecEventType, Served, get_rec_signals
from app.recs.web_search import build_query, get_web_search
from app.scoring.scorer import word_count
from app.store.content_repo import get_content_store

log = logging.getLogger("app.recs")
router = APIRouter()

WEB_TRIGGERS = 3  # concepts searched per article view (× formats → cached calls)
WEB_PER_QUERY = 3  # results per (concept, format) considered for ranking
WEB_RANK_DECAY = 0.12
MAX_EVENTS = 50


class TriggerOut(BaseModel):
    id: str
    label: str


class RecItem(BaseModel):
    id: str
    kind: Literal["library", "web"]
    relation: Relation
    relation_label: str
    format: Format
    title: str
    url: str
    content_id: str | None  # library items open in the reader
    source: str
    duration_or_read_time: int | None  # seconds
    snippet: str
    thumbnail: str | None
    published_at: str | None
    why: str
    triggers: list[TriggerOut]
    score: float


class RecsResponse(BaseModel):
    content_id: str
    persona: PersonaKey | None  # demo persona; None for a signed-in reader
    prefer: Format | None
    items: list[RecItem]
    pending: bool  # web lookups still running: poll again shortly
    web_formats: list[Format]  # formats a web provider is configured for


class RecEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=64)
    type: RecEventType
    item_id: str = Field(min_length=1, max_length=80)


class RecEventsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    persona: PersonaKey | None = None  # honoured for anonymous readers only
    events: list[RecEvent] = Field(max_length=MAX_EVENTS)


class OpenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(max_length=MAX_URL_CHARS)


class OpenResponse(BaseModel):
    content_id: str
    new: bool


# Library index per catalog version (pure derivation over all docs).
_index: tuple[int, LibraryIndex] | None = None


async def _library_index() -> LibraryIndex:
    global _index
    docs = await catalog.all_docs()
    if _index is None or _index[0] != catalog.version():
        _index = (catalog.version(), LibraryIndex.build(docs))
    return _index[1]


def _quote(label: str) -> str:
    return f"‘{label}’"


def _why(relation: Relation, trigger: str | None, detail: str | None, source: str) -> str:
    c = _quote(trigger) if trigger else None
    if relation == "primer":
        if c and detail and detail != trigger:
            return f"Because {c} was new to you; starts with {_quote(detail)}"
        return f"Because {c} was new to you" if c else "A gentler start on this topic"
    if relation == "deeper":
        if c and detail:
            return f"You met {c}; this builds on it with {_quote(detail)}"
        return f"Builds on {c}" if c else "Goes further on this topic"
    if relation == "angle":
        who = detail or source
        return (
            f"The same ideas as {c}, seen from {who}" if c else f"The same ideas, seen from {who}"
        )
    if relation == "same_story":
        return f"The same story, told by {source}"
    return f"Because {c} was new to you" if c else "An explainer on this topic"


def _published(doc: ContentDoc) -> str | None:
    """Encyclopedia pages are evergreen: no freshness decay for them."""
    return None if is_wikipedia(doc) else doc.published


def _read_time(doc: ContentDoc) -> int:
    return word_count(doc) * 60 // 230


def _library_item(
    cand: LibraryCandidate, doc: ContentDoc, graph: ConceptGraph, score: float
) -> RecItem:
    triggers = [TriggerOut(id=t, label=c.label) for t in cand.trigger_ids if (c := graph.get(t))]
    first = triggers[0].label if triggers else None
    return RecItem(
        id=f"lib:{doc.content_id}",
        kind="library",
        relation=cand.relation,
        relation_label=RELATION_LABEL[cand.relation],
        format="article",
        title=doc.title,
        url=doc.final_url or doc.url,
        content_id=doc.content_id,
        source=doc.site,
        duration_or_read_time=_read_time(doc),
        snippet=doc.description or "",
        thumbnail=doc.image,
        published_at=doc.published,
        why=_why(cand.relation, first, cand.detail, doc.site),
        triggers=triggers,
        score=round(score, 4),
    )


def _web_id(url: str) -> str:
    return "web:" + hashlib.sha1(url.encode()).hexdigest()[:16]


def _web_item(r: WebResult, trigger_id: str, graph: ConceptGraph, score: float) -> RecItem:
    concept = graph.get(trigger_id)
    label = concept.label if concept else None
    return RecItem(
        id=_web_id(r.url),
        kind="web",
        relation="explainer",
        relation_label=RELATION_LABEL["explainer"],
        format=r.format,
        title=r.title,
        url=r.url,
        content_id=None,
        source=r.source,
        duration_or_read_time=r.duration_or_read_time,
        snippet=r.snippet,
        thumbnail=r.thumbnail,
        published_at=r.published_at,
        why=_why("explainer", label, None, r.source),
        triggers=[TriggerOut(id=trigger_id, label=label)] if label else [],
        score=round(score, 4),
    )


@router.get("/content/{content_id}/recommendations", response_model=RecsResponse)
async def recommendations(
    content_id: str,
    ctx: Annotated[ReaderContext, Depends(reader_context)],
    prefer: Format | None = None,
) -> RecsResponse:
    doc = await get_content_store().get(content_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="content not found")
    graph = get_graph()
    theta = ctx.theta
    spans = (await score_for(ctx, doc, "balanced", datetime.now(UTC))).spans
    triggers = [s.concept_id for s in spans]  # highest score first

    index = await _library_index()
    lib = library_candidates(index, doc, graph, theta, triggers)

    web = get_web_search()
    known_urls = {d.final_url or d.url for d in index.docs.values()}
    web_results: dict[str, tuple[WebResult, str, float]] = {}
    pending = False
    anonymous = ctx.caller.is_anonymous
    may_search = not anonymous or await web.anonymous_allowance_left()
    top = spans[:WEB_TRIGGERS]
    best = top[0].score if top else 1.0
    for span in top:
        for fmt in sorted(web.formats):
            query = build_query(span.label, fmt, span.domain)
            results, fresh = await web.cached(span.concept_id, fmt, query)
            if not fresh and may_search:
                web.refresh(span.concept_id, span.label, fmt, span.domain, anonymous=anonymous)
            pending = pending or web.pending(span.concept_id, fmt)
            for rank, r in enumerate(results[:WEB_PER_QUERY]):
                if r.url in known_urls:
                    continue
                relevance = (span.score / best) * (1 - WEB_RANK_DECAY * rank)
                prev = web_results.get(r.url)
                if prev is None or relevance > prev[2]:
                    web_results[r.url] = (r, span.concept_id, relevance)

    candidates = [
        Candidate(
            f"lib:{c.content_id}",
            c.relation,
            "article",
            c.relevance,
            _published(index.docs[c.content_id]),
            _read_time(index.docs[c.content_id]),
        )
        for c in lib
    ] + [
        Candidate(
            _web_id(r.url),
            "explainer",
            r.format,
            rel,
            r.published_at,
            r.duration_or_read_time,
            kind="web",
        )
        for r, _, rel in web_results.values()
    ]
    signals = get_rec_signals()
    now = datetime.now(UTC)
    chosen = select(
        candidates,
        await signals.signals(ctx.uid, ctx.rec_key),
        PERSONA_FORMAT_PRIORS[ctx.rec_key],
        now,
        prefer,
    )

    lib_by_key = {(f"lib:{c.content_id}", c.relation): c for c in lib}
    web_by_id = {_web_id(url): v for url, v in web_results.items()}
    items: list[RecItem] = []
    for cand, s in chosen:
        if (lc := lib_by_key.get((cand.id, cand.relation))) is not None:
            items.append(_library_item(lc, index.docs[lc.content_id], graph, s))
        else:
            r, trigger_id, _ = web_by_id[cand.id]
            items.append(_web_item(r, trigger_id, graph, s))
    await signals.remember_served(
        ctx.uid, ctx.rec_key, {i.id: Served(i.format, i.relation) for i in items}, now
    )
    return RecsResponse(
        content_id=content_id,
        persona=ctx.persona,
        prefer=prefer,
        items=items,
        pending=pending,
        web_formats=[f for f in FORMATS if f in web.formats],
    )


@router.post("/recs/events")
async def rec_events(
    body: RecEventsRequest, caller: Annotated[Caller, Depends(current_caller)]
) -> dict[str, int]:
    """Idempotent by event id; only items we served to this reader count."""
    key = scope_persona(caller, body.persona) or DEFAULT_KEY
    applied = await get_rec_signals().apply(
        caller.uid, key, [(e.id, e.type, e.item_id) for e in body.events]
    )
    return {"applied": applied, "ignored": len(body.events) - applied}


@router.post("/recs/open", response_model=OpenResponse)
async def open_web_article(
    body: OpenRequest,
    caller: Annotated[Caller, Depends(current_caller)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> OpenResponse | JSONResponse:
    """Ingest a web article through safe_fetch and the normal pipeline, within the daily cap."""
    try:
        validate_url(body.url)
    except FetchError as exc:
        return _error(FETCH_ERROR_STATUS[exc.code], exc.code, exc.message)
    known = await get_content_store().get(url_hash(body.url)) is not None
    if not known and not await quota.reserve(caller, settings):
        return quota.cap_reached(caller, settings, "Use “Open original” for this one.")
    try:
        doc = await ingest_url(body.url, source="user_ingested")
    except Exception as exc:
        if not known:
            await quota.refund(caller)
        if isinstance(exc, FetchError | llm.BudgetExceeded | llm.LLMUnavailable | llm.LLMRejected):
            return _ingest_error(exc)
        raise
    if not known:
        catalog.add(doc)
    log.info("rec opened", extra={"content_id": doc.content_id, "new": not known})
    return OpenResponse(content_id=doc.content_id, new=not known)
