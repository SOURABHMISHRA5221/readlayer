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
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.auth import Caller, current_caller
from app.config import Settings, get_settings
from app.content import catalog
from app.content.router import doc_or_error, score_for
from app.context import ReaderContext, hidden_ids, reader_context, scope_persona
from app.graph.graph import ConceptGraph
from app.graph.loader import get_graph
from app.ingest import quota
from app.ingest.models import NOT_CORPUS, ContentDoc, is_corpus
from app.ingest.router import (
    FETCH_ERROR_STATUS,
    INGEST_ERRORS,
    MAX_URL_CHARS,
    _error,
    _ingest_error,
    fetch_and_extract,  # lazy: loads the ingestion pipeline on first use
)
from app.ingest.safe_fetch import FetchError, validate_url
from app.ingest.urls import url_hash
from app.media import urls as media_urls
from app.media.openable import open_here
from app.reader.state import PersonaKey
from app.recs.feed_rank import key_ideas
from app.recs.library import LibraryCandidate, LibraryIndex, is_wikipedia, library_candidates
from app.recs.models import FORMATS, Format, Relation, WebResult
from app.recs.rank import RELATION_LABEL, Candidate, one_per_format, prior_for, score, select
from app.recs.state import DEFAULT_KEY, RecEventType, Served, get_rec_signals
from app.recs.web_search import (
    STORY_FORMATS,
    WebSearch,
    build_query,
    get_web_search,
    story_key,
    story_relevant,
    title_words,
)
from app.scoring.scorer import word_count
from app.store.content_repo import get_content_store
from app.store.docstore import get_doc_store
from app.store.pending_repo import get_pending_repo
from app.store.reader_repo import ReaderRepo

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
    # Opens in Gloss (library items, articles, videos within the media caps) or only at the
    # source.
    open_here: bool = True


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
    # False while the article is fetched but not analysed: the reader shows it at once and
    # calls POST /v1/content/{id}/analyse for the notes (two-phase "Open here").
    ready: bool
    kind: Literal["article", "video", "podcast"] = "article"
    # What the page calls next: "transcribe" (a recording with no transcript yet), "analyse",
    # or None when ready.
    stage: Literal["transcribe", "analyse"] | None = None


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


STORY_RELATIONS = frozenset({"same_story", "angle"})


def _key_idea_why(item: RecItem) -> str:
    label = item.triggers[0].label if item.triggers else None
    return f"On {_quote(label)}, a key idea here" if label else "On a key idea here"


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


STORY_LEAD = 2  # story items first at the end of the article (decision 69 B2)
STORY_RELEVANCE = 1.0
STORY_LABELS = 3  # the article's top key ideas a story result may name


@dataclass(frozen=True)
class _Story:
    results: list[WebResult]
    pending: bool


async def _story_results(
    basis: str, doc: ContentDoc, spans: list["_Trigger"], web: WebSearch, known_urls: set[str],
    may_search: bool, anonymous: bool,
) -> _Story:  # fmt: skip
    """More coverage of this article's story (decision 69 B2): corpus articles only, so the title
    of a page a reader brought in never leaves (DESIGN §16.3). One search per format ever."""
    if basis != "story" or not is_corpus(doc) or not doc.title:
        return _Story([], False)
    own = {url_hash(u) for u in (doc.url, doc.final_url) if u}
    labels = [s.label for s in spans[:STORY_LABELS]]
    words = title_words(doc.title)

    def keep(r: WebResult) -> bool:
        return url_hash(r.url) not in own and story_relevant(r, labels, words)

    results: list[WebResult] = []
    pending = False
    for fmt in STORY_FORMATS:
        if fmt not in web.formats:
            continue
        entry = await web.cached_entry(story_key(doc.content_id), fmt)
        if entry is None:
            if may_search:
                web.refresh_story(doc.content_id, doc.title, fmt, keep, anonymous=anonymous)
            pending = pending or web.pending(story_key(doc.content_id), fmt)
            continue
        results += [r for r in entry.results[:WEB_PER_QUERY] if r.url not in known_urls and keep(r)]
    return _Story(results, pending)


SPREAD = 0.5  # basis=story: each idea's n-th item counts SPREAD**n (decision 69 B3)


Key = tuple[str, str]  # (candidate id, relation): a library doc can be a primer and an angle


def _idea_items(
    lib: Sequence[LibraryCandidate], web_results: Mapping[str, tuple[WebResult, str, float]]
) -> list[tuple[Key, str | None, float]]:
    """Every story-basis candidate with the idea it follows (decision 69 B3): a library item's
    first trigger (the idea its "On ‘X’" reason names), a key-idea search result's idea. A library
    same_story item follows no idea (its reason names the source, and its triggers are just the
    shared ones in alphabetical order), so it is neither spread nor capped."""
    items: list[tuple[Key, str | None, float]] = [
        ((f"lib:{c.content_id}", c.relation),
         c.trigger_ids[0] if c.trigger_ids and c.relation != "same_story" else None, c.relevance)
        for c in lib
    ]  # fmt: skip
    items += [((_web_id(r.url), "explainer"), tid, rel) for r, tid, rel in web_results.values()]
    return items


def _spread(items: list[tuple[Key, str | None, float]]) -> dict[Key, float]:
    """(key, idea, relevance) → relevance × SPREAD**(items of the same idea ranked above it), so
    the end of the article follows several of its ideas, not just the top one (Sourabh: "the
    bottom articles still focusing on single word"). Items with no idea keep their relevance."""
    out: dict[Key, float] = {}
    seen: dict[str, int] = {}
    for key, idea, rel in sorted(items, key=lambda t: (-t[2], t[0])):
        n = seen.get(idea, 0) if idea else 0
        out[key] = rel * SPREAD**n
        if idea:
            seen[idea] = n + 1
    return out


PER_IDEA = 2


def _cap_per_idea(
    chosen: list[tuple[Candidate, float]],
    candidates: list[Candidate],
    idea_of: Mapping[Key, str],
    reselect: Callable[[list[Candidate]], list[tuple[Candidate, float]]],
) -> list[tuple[Candidate, float]]:
    """While one idea has more than PER_IDEA picks, set its weakest pick aside and rank again, so
    the next best item of another idea (any format) takes the place. An idea keeps more than
    PER_IDEA only when nothing else can fill the list: the list never shrinks (a page with one
    linked idea keeps its six items). Bounded by the candidates."""
    banned: set[str] = set()
    for _ in range(len(candidates)):
        count: dict[str, list[tuple[Candidate, float]]] = {}
        for cs in chosen:
            if (idea := idea_of.get((cs[0].id, cs[0].relation))) is not None:
                count.setdefault(idea, []).append(cs)
        over = [v for v in count.values() if len(v) > PER_IDEA]
        if not over:
            return chosen
        weakest = min(over[0], key=lambda cs: (cs[1], cs[0].id))
        again = reselect([c for c in candidates if c.id not in banned | {weakest[0].id}])
        if len(again) < len(chosen):
            return chosen  # nothing else to fill the place
        banned.add(weakest[0].id)
        chosen = again
    return chosen


def _lead_with_story(
    chosen: list[tuple[Candidate, float]],
    candidates: list[Candidate],
    story_ids: Mapping[str, Any],
    alive: Callable[[Candidate], bool],
) -> list[tuple[Candidate, float]]:
    """Up to STORY_LEAD story items lead, included even when `select` left them out: a same-story
    item scores below a key-idea explainer, so ranking alone dropped them all (live check,
    2026-10-17). Never one the reader dismissed or finished (`alive`, the score `select` uses).
    They take the places of the lowest-ranked items; the list doesn't grow."""
    picked = [c for c in chosen if c[0].id in story_ids and c[0].relation == "same_story"]
    taken = {c[0].id for c in chosen}
    floor = min((s for _, s in chosen), default=STORY_RELEVANCE)
    extra = [(c, floor) for c in candidates
             if c.relation == "same_story" and c.id in story_ids and c.id not in taken
             and alive(c)]  # fmt: skip
    lead = (picked + extra)[:STORY_LEAD]
    lead_ids = {c.id for c, _ in lead}
    rest = [c for c in chosen if c[0].id not in lead_ids]
    size = max(len(chosen), len(lead))
    return lead + rest[: size - len(lead)]


def _story_item(r: WebResult, score: float) -> RecItem:
    return RecItem(
        id=_web_id(r.url),
        kind="web",
        relation="same_story",
        relation_label=RELATION_LABEL["same_story"],
        format=r.format,
        title=r.title,
        url=r.url,
        content_id=None,
        source=r.source,
        duration_or_read_time=r.duration_or_read_time,
        snippet=r.snippet,
        thumbnail=r.thumbnail,
        published_at=r.published_at,
        why="More on this story",
        triggers=[],
        score=round(score, 4),
    )


@dataclass(frozen=True)
class _Trigger:
    concept_id: str
    label: str
    domain: str
    weight: float


async def _triggers(
    basis: str, ctx: ReaderContext, doc: ContentDoc, graph: ConceptGraph
) -> list[_Trigger]:
    """ "consumer": the concepts new to this person, highest score first (the old web's end of
    article list). "article" (decision 67 N1, the card chips) and "story" (decision 69 B, the end
    of the article): the article's own key ideas by salience, the same for everyone."""
    if basis in ("article", "story"):
        ideas, _ = key_ideas(doc, graph)
        return [_Trigger(c.id, c.label, c.domain, 1.0 - 0.1 * i) for i, c in enumerate(ideas)]
    spans = (await score_for(ctx, doc, "balanced", datetime.now(UTC))).spans
    return [_Trigger(s.concept_id, s.label, s.domain, s.score) for s in spans]


@router.get("/content/{content_id}/recommendations", response_model=RecsResponse)
async def recommendations(
    content_id: str,
    ctx: Annotated[ReaderContext, Depends(reader_context)],
    prefer: Format | None = None,
    basis: Literal["consumer", "article", "story"] = "consumer",
) -> RecsResponse:
    doc = await doc_or_error(content_id, ctx)
    graph = get_graph()
    theta = ctx.theta
    spans = await _triggers(basis, ctx, doc, graph)
    web = get_web_search()
    if not spans and basis in ("article", "story"):  # nothing linked: nothing to follow
        return RecsResponse(
            content_id=content_id, persona=ctx.persona, prefer=prefer, items=[], pending=False,
            web_formats=[f for f in FORMATS if f in web.formats],
        )  # fmt: skip
    triggers = [s.concept_id for s in spans]

    index = await _library_index()
    hidden = hidden_ids(index.docs.values(), ctx)  # per request, after the shared index
    lib = library_candidates(index, doc, graph, theta, triggers, hidden)

    known_urls = {d.final_url or d.url for cid, d in index.docs.items() if cid not in hidden}
    web_results: dict[str, tuple[WebResult, str, float]] = {}
    pending = False
    anonymous = ctx.caller.is_anonymous
    may_search = not anonymous or await web.anonymous_allowance_left()
    top = spans[:WEB_TRIGGERS]
    best = top[0].weight if top else 1.0
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
                relevance = (span.weight / best) * (1 - WEB_RANK_DECAY * rank)
                prev = web_results.get(r.url)
                if prev is None or relevance > prev[2]:
                    web_results[r.url] = (r, span.concept_id, relevance)

    story = await _story_results(basis, doc, spans, web, known_urls, may_search, anonymous)
    pending = pending or story.pending

    ideas = _idea_items(lib, web_results) if basis == "story" else []
    weight = _spread(ideas)
    candidates = [
        Candidate(
            f"lib:{c.content_id}",
            c.relation,
            "article",
            weight.get((f"lib:{c.content_id}", c.relation), c.relevance),
            _published(index.docs[c.content_id]),
            _read_time(index.docs[c.content_id]),
        )
        for c in lib
    ] + [
        Candidate(
            _web_id(r.url),
            "explainer",
            r.format,
            weight.get((_web_id(r.url), "explainer"), rel),
            r.published_at,
            r.duration_or_read_time,
            kind="web",
        )
        for r, _, rel in web_results.values()
    ] + [
        Candidate(_web_id(r.url), "same_story", r.format, STORY_RELEVANCE, r.published_at,
                  r.duration_or_read_time, kind="web")
        for r in story.results
    ]  # fmt: skip
    signals = get_rec_signals()
    now = datetime.now(UTC)
    reader_signals = await signals.signals(ctx.uid, ctx.rec_key)
    prior = prior_for(ctx.rec_key, ctx.user.formats)
    chosen = select(candidates, reader_signals, prior, now, prefer)
    if basis == "story":  # at most PER_IDEA items follow any one idea (decision 69 B3)
        idea_of = {key: idea for key, idea, _ in ideas if idea is not None}

        def again(cs: list[Candidate]) -> list[tuple[Candidate, float]]:
            return select(cs, reader_signals, prior, now, prefer)

        chosen = _cap_per_idea(chosen, candidates, idea_of, again)
    if basis == "article":
        chosen = one_per_format(chosen, ctx.user.formats)
    story_by_id = {_web_id(r.url): r for r in story.results}
    if basis == "story":
        chosen = _lead_with_story(
            chosen, candidates, story_by_id,
            lambda c: score(c, reader_signals, prior, now, prefer) > 0,  # never a dismissed one
        )  # fmt: skip

    lib_by_key = {(f"lib:{c.content_id}", c.relation): c for c in lib}
    web_by_id = {_web_id(url): v for url, v in web_results.items()}
    items: list[RecItem] = []
    for cand, s in chosen:
        if (lc := lib_by_key.get((cand.id, cand.relation))) is not None:
            items.append(_library_item(lc, index.docs[lc.content_id], graph, s))
        else:
            if cand.relation == "same_story" and cand.id in story_by_id:
                item = _story_item(story_by_id[cand.id], s)
            else:
                r, trigger_id, _ = web_by_id[cand.id]
                item = _web_item(r, trigger_id, graph, s)
            here = await open_here(
                item.url, item.format, item.duration_or_read_time, get_settings(), anonymous
            )
            items.append(item.model_copy(update={"open_here": here}))
    if basis == "article":
        items = [i.model_copy(update={"why": _key_idea_why(i)}) for i in items]
    elif basis == "story":  # the same story elsewhere keeps its reason; the rest follow a key idea
        items = [
            i if i.relation in STORY_RELATIONS else i.model_copy(update={"why": _key_idea_why(i)})
            for i in items
        ]
    if ctx.user.may_record:  # nothing recorded for a signed-in reader before consent
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
    """Idempotent by event id; only items we served to this reader count. Nothing is recorded
    for a signed-in reader before consent (DESIGN §11.4)."""
    if (
        not caller.is_anonymous
        and not (await ReaderRepo(get_doc_store()).get_user(caller.uid)).may_record
    ):
        return {"applied": 0, "ignored": len(body.events)}
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
    """Phase 1 of "Open here": fetch through safe_fetch and extract, within the daily cap. The
    analysis (phase 2) is its own request, so the reader sees the article in seconds."""
    try:
        validate_url(body.url)
    except FetchError as exc:
        return _error(FETCH_ERROR_STATUS[exc.code], exc.code, exc.message)
    if (media := media_urls.classify(body.url)) is not None:
        return await _open_media(media, caller, settings)
    content_id = url_hash(body.url)
    existing = await get_content_store().get(content_id)
    if existing is not None:
        if not is_corpus(existing):
            await _remember_ingested(caller, content_id)
        log.info("rec opened", extra={"content_id": content_id, "new": False, "ready": True})
        return OpenResponse(content_id=content_id, new=False, ready=True)
    pending = await get_pending_repo().get(content_id)
    if pending is not None:  # fetched by someone else, not analysed yet
        if pending.source in NOT_CORPUS:
            await _remember_ingested(caller, content_id)
        log.info("rec opened", extra={"content_id": content_id, "new": False, "ready": False})
        return OpenResponse(content_id=content_id, new=False, ready=False, stage="analyse")
    if not await quota.reserve(caller, settings):
        return quota.cap_reached(caller, settings, "Use “Open original” for this one.")
    try:  # growth slots are taken when …/analyse runs growth (M9)
        await fetch_and_extract(body.url, "user_ingested")
    except Exception as exc:
        await quota.refund(caller)
        if isinstance(exc, INGEST_ERRORS):
            return _ingest_error(exc)
        raise
    await _remember_ingested(caller, content_id)
    log.info("rec opened", extra={"content_id": content_id, "new": True, "ready": False})
    return OpenResponse(content_id=content_id, new=True, ready=False, stage="analyse")


async def _open_media(
    media: media_urls.Media, caller: Caller, settings: Settings
) -> OpenResponse | JSONResponse:
    """A YouTube video or podcast episode (DESIGN §21): checks and a pending doc, no model call.
    The page then calls .../transcribe and .../analyse."""
    from app import llm
    from app.media.refusals import MediaCapReached, MediaRefused, MediaUnavailable, message
    from app.media.service import open_media

    try:
        opened = await open_media(media, caller, settings)
    except MediaRefused as exc:
        return _error(422, exc.code, message(exc.code))
    except MediaCapReached:
        return _media_cap_reached(caller, settings)
    except MediaUnavailable:
        return _error(503, "media_unavailable", message("media_unavailable"), retry_after=60)
    except llm.BudgetExceeded as exc:
        return _ingest_error(exc)
    await _remember_ingested(caller, opened.content_id)
    log.info(
        "rec opened",
        extra={"content_id": opened.content_id, "new": opened.new, "stage": opened.stage},
    )
    return OpenResponse(
        content_id=opened.content_id,
        new=opened.new,
        ready=opened.stage is None,
        kind=media_urls.kind(media),
        stage=opened.stage,
    )


def _media_cap_reached(caller: Caller, settings: Settings) -> JSONResponse:
    if caller.is_anonymous:
        limit = "The demo can open only a few new videos and podcasts a day."
        more = " Sign in with Google for more."
    else:
        limit = f"You can open {settings.media_daily_cap} new videos and podcasts a day."
        more = " Or try again tomorrow."
    return _error(429, "media_cap_reached", f"{limit} Use “Open original” for this one.{more}")


async def _remember_ingested(caller: Caller, content_id: str) -> None:
    """This reader brought the page in: their library and Up next list it (M7.5)."""
    await ReaderRepo(get_doc_store()).add_ingested(
        caller.uid, content_id, datetime.now(UTC).isoformat()
    )
