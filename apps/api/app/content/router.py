"""Read side of content for the reader UI: library list, article body, annotations.

Annotations come from the gap scorer (app/scoring/scorer.py, DESIGN §5–6) over the reader's
own graph, or the demo persona's. No LLM call on this path.
"""

import logging
import time
from collections import deque
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app import ratelimit
from app.auth import Caller, current_caller
from app.config import Settings, get_settings
from app.content import catalog
from app.content.access import require_readable
from app.content.summary import article_domain
from app.context import ReaderContext, hidden_ids, reader_context
from app.graph.loader import get_graph
from app.ingest.models import ContentDoc, Media, PendingDoc
from app.reader.model import Band
from app.reader.state import Density, PersonaKey
from app.scoring import scorer
from app.scoring.scorer import Annotations, ExplainerRef, ScoringInputs
from app.store.content_repo import get_content_store
from app.store.docstore import get_doc_store
from app.store.pending_repo import MAX_ATTEMPTS, get_pending_repo
from app.store.reader_repo import ReaderRepo

log = logging.getLogger(__name__)
router = APIRouter()

MAX_QUERY_CHARS = 200
LATENCY_WINDOW = 200  # recent scoring times kept for the p95 log line
LATENCY_LOG_EVERY = 50


class ContentSummary(BaseModel):
    id: str
    title: str
    site: str
    word_count: int
    description: str | None
    author: str | None
    published: str | None
    image: str | None
    domain: str | None
    # Span annotations this persona would get at this density: "N concepts new to you".
    concepts_new: int
    format: Literal["article", "video", "podcast"] = "article"


class ParagraphOut(BaseModel):
    id: str
    text: str
    start_s: int | None = None  # transcript paragraphs: where it starts in the recording


class MediaOut(BaseModel):
    """The recording a transcript was made from (DESIGN §21); the page plays it from here."""

    kind: Literal["video", "podcast"]
    video_id: str | None
    audio_url: str | None
    duration_s: int


class RefusalOut(BaseModel):
    code: str
    message: str


class ContentDetail(BaseModel):
    id: str
    title: str
    site: str
    url: str
    word_count: int
    description: str | None
    author: str | None
    published: str | None
    image: str | None
    domain: str | None
    paragraphs: list[ParagraphOut]
    # "analysing": fetched, notes not ready yet; the client calls POST .../analyse.
    # "transcribing": a recording with no transcript yet (paragraphs empty); the client calls
    # POST .../transcribe. "refused" (with `refusal`) and "failed" (attempts used up): the page
    # shows the message with "Open original" and stops calling.
    status: Literal["transcribing", "analysing", "ready", "refused", "failed"]
    media: MediaOut | None = None
    refusal: RefusalOut | None = None


class AnchorOut(BaseModel):
    exact: str
    prefix: str
    suffix: str
    start: int
    end: int


class AnnotationDebug(BaseModel):
    p_know: float
    salience: float
    span_score: float
    domain: str
    base_difficulty: float


class AnnotationOut(BaseModel):
    id: str
    kind: Literal["span"] = "span"
    anchor: AnchorOut
    paragraph_id: str
    score: float
    concept_id: str
    label: str
    definition: str
    domain: str
    prerequisites: list[str]
    band: Band  # the reader's band for the concept (what the explanation is pitched at)
    level: Literal["new", "refresher"]  # highlight style (Design pass A1)
    debug: AnnotationDebug | None = None


class ParagraphMarkerOut(BaseModel):
    """ "What this paragraph is saying" margin marker (shown from M6)."""

    id: str
    kind: Literal["paragraph"] = "paragraph"
    paragraph_id: str
    score: float
    domain: str | None


class PrereadStepOut(BaseModel):
    concept_id: str
    label: str
    definition: str
    content_id: str | None  # a corpus article explaining the concept, else show the definition
    title: str | None
    known: bool = False  # where the path starts from, shown ticked (Design pass A2)


class PrereadOut(BaseModel):
    """Pre-read card: prerequisites to meet first, most basic first (shown from M6)."""

    id: str = "preread"
    kind: Literal["preread"] = "preread"
    score: float
    concept_id: str
    label: str
    steps: list[PrereadStepOut]


class PromptOut(BaseModel):
    """ "Know this?" uncertainty prompt (shown from M6)."""

    id: str
    kind: Literal["prompt"] = "prompt"
    anchor: AnchorOut
    paragraph_id: str
    concept_id: str
    label: str


AnyAnnotation = Annotated[
    AnnotationOut | ParagraphMarkerOut | PrereadOut | PromptOut, Field(discriminator="kind")
]


class AnnotationsResponse(BaseModel):
    content_id: str
    persona: PersonaKey | None  # demo persona; None for a signed-in reader
    density: Density
    count: int  # span annotations
    annotations: list[AnyAnnotation]  # spans first (ranked), then paragraphs, pre-read, prompt


# Library rows per (catalog version, reader state revision, density): pure computation over
# the shared catalog, cached because the list endpoint is hit on every library view. Demo
# readers who haven't interacted share their persona template's revision. Bounded.
_rows: dict[tuple[int, str, str, Density], list[ContentSummary]] = {}  # catalog, graph, view
MAX_CACHED_VIEWS = 64
# Catalog-derived scoring inputs, rebuilt when the doc set changes.
_index: tuple[int, dict[str, ContentDoc], dict[str, ExplainerRef]] | None = None
_latencies: deque[float] = deque(maxlen=LATENCY_WINDOW)
_scored = 0


def reset_catalog() -> None:
    global _index
    catalog.reset()
    _rows.clear()
    _index = None


async def refresh_growth() -> None:
    """Pick up concepts grown on other instances (at most once per GROWTH_REFRESH_S; a
    Firestore query, never an LLM call). Off while growth is off."""
    if get_settings().growth_enabled:
        from app.graph.refresh import get_refresher

        await get_refresher().maybe_refresh()


async def _catalog_index() -> tuple[dict[str, ContentDoc], dict[str, ExplainerRef]]:
    global _index
    docs = await catalog.all_docs()
    version = catalog.version()
    if _index is None or _index[0] != version:
        _index = (version, {d.content_id: d for d in docs}, scorer.explainer_index(docs))
    return _index[1], _index[2]


async def _inputs(ctx: ReaderContext, doc: ContentDoc, now: datetime) -> ScoringInputs:
    by_id, explainers = await _catalog_index()
    return ScoringInputs(
        engaged_entities=scorer.engaged_entities(
            by_id, ctx.state.recent_contents(now), doc.content_id
        ),
        explainers=explainers,
        prompted_today=tuple(ctx.user.prompts.get(now.date().isoformat(), [])),
        prompts_allowed=not ctx.user.learning_paused,
    )


def p95(samples: list[float]) -> float:
    ordered = sorted(samples)
    return ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))] if ordered else 0.0


def _record_latency(ms: float) -> None:
    global _scored
    _latencies.append(ms)
    _scored += 1
    if _scored % LATENCY_LOG_EVERY == 0:
        log.info(
            "annotation scoring latency",
            extra={"p95_ms": round(p95(list(_latencies)), 2), "window": len(_latencies)},
        )


async def score_for(
    ctx: ReaderContext, doc: ContentDoc, density: Density, now: datetime
) -> Annotations:
    """The reader's annotations for one article (also the recommender's triggers)."""
    inputs = await _inputs(ctx, doc, now)
    started = time.perf_counter()
    result = scorer.annotate(doc, get_graph(), ctx.state, density, now, inputs)
    _record_latency((time.perf_counter() - started) * 1000)
    return result


async def _summaries(ctx: ReaderContext, density: Density) -> list[ContentSummary]:
    docs = await catalog.all_docs()
    key = (catalog.version(), get_graph().version, ctx.view_key, density)
    if key not in _rows:
        graph = get_graph()
        now = datetime.now(UTC)
        _, explainers = await _catalog_index()
        inputs = ScoringInputs(explainers=explainers)
        if len(_rows) >= MAX_CACHED_VIEWS:
            _rows.pop(next(iter(_rows)))
        _rows[key] = [
            _summary(
                d,
                article_domain(d, graph),
                len(scorer.annotate(d, graph, ctx.state, density, now, inputs).spans),
            )
            for d in docs
        ]
    return _rows[key]


def _summary(doc: ContentDoc, domain: str | None, concepts_new: int) -> ContentSummary:
    return ContentSummary(
        id=doc.content_id,
        title=doc.title,
        site=doc.site,
        word_count=scorer.word_count(doc),
        description=doc.description,
        author=doc.author,
        published=doc.published,
        image=doc.image,
        domain=domain,
        concepts_new=concepts_new,
        format=media_out(doc.media).kind if doc.media else "article",
    )


async def doc_or_error(content_id: str, ctx: ReaderContext) -> ContentDoc:
    """An analysed article this reader may read; 409 while it is fetched but not analysed yet,
    else 404."""
    doc = await get_content_store().get(content_id)
    if doc is not None:
        await require_readable(doc, ctx.uid, ctx.ingested)
        return doc
    if (pending := await get_pending_repo().get(content_id)) is not None:
        await require_readable(pending, ctx.uid, ctx.ingested)
        raise HTTPException(status_code=409, detail="content_pending")
    raise HTTPException(status_code=404, detail="content not found")


@router.get("/content", response_model=list[ContentSummary])
async def list_content(
    ctx: Annotated[ReaderContext, Depends(reader_context)],
    q: Annotated[str, Query(max_length=MAX_QUERY_CHARS)] = "",
    density: Density | None = None,
) -> list[ContentSummary]:
    await refresh_growth()
    needle = q.strip().casefold()
    items = await _summaries(ctx, density or ctx.density)
    # Other readers' pages are dropped per request, after the shared row cache (M7.5).
    hidden = hidden_ids(await catalog.all_docs(), ctx)
    items = [s for s in items if s.id not in hidden]
    if not needle:
        return items
    return [s for s in items if needle in s.title.casefold() or needle in s.site.casefold()]


@router.get("/content/{content_id}", response_model=ContentDetail)
async def get_content(
    content_id: str, caller: Annotated[Caller, Depends(current_caller)]
) -> ContentDetail:
    await refresh_growth()
    doc = await get_content_store().get(content_id)
    if doc is None:
        pending = await get_pending_repo().get(content_id)
        if pending is None:
            raise HTTPException(status_code=404, detail="content not found")
        await require_readable(pending, caller.uid)
        return _pending_detail(pending)
    await require_readable(doc, caller.uid)
    return ContentDetail(
        id=doc.content_id,
        title=doc.title,
        site=doc.site,
        url=doc.final_url or doc.url,
        word_count=scorer.word_count(doc),
        description=doc.description,
        author=doc.author,
        published=doc.published,
        image=doc.image,
        domain=article_domain(doc, get_graph()),
        paragraphs=[ParagraphOut(id=p.id, text=p.text, start_s=p.start_s) for p in doc.paragraphs],
        status="ready",
        media=media_out(doc.media),
    )


def media_out(media: Media | None) -> MediaOut | None:
    if media is None:
        return None
    return MediaOut(
        kind="video" if media.kind == "youtube" else "podcast",
        video_id=media.video_id,
        audio_url=media.audio_url,
        duration_s=media.duration_s,
    )


def _pending_status(doc: PendingDoc) -> str:
    if doc.refused:
        return "refused"
    attempts = doc.transcribe_attempts if doc.stage == "transcribe" else doc.attempts
    if attempts >= MAX_ATTEMPTS:
        return "failed"
    return "transcribing" if doc.stage == "transcribe" else "analysing"


def _pending_detail(doc: PendingDoc) -> ContentDetail:
    """A fetched article still being analysed: shown at once, notes follow (two-phase). A
    recording is shown (its player) before its transcript exists."""
    from app.media.refusals import message

    return ContentDetail(
        id=doc.content_id,
        title=doc.title,
        site=doc.site,
        url=doc.final_url or doc.url,
        word_count=sum(len(p.text.split()) for p in doc.paragraphs),
        description=doc.description,
        author=doc.author,
        published=doc.published,
        image=doc.image,
        domain=None,
        paragraphs=[ParagraphOut(id=p.id, text=p.text, start_s=p.start_s) for p in doc.paragraphs],
        status=_pending_status(doc),
        media=media_out(doc.media),
        refusal=RefusalOut(code=doc.refused, message=message(doc.refused)) if doc.refused else None,
    )


@router.get(
    "/content/{content_id}/annotations",
    response_model=AnnotationsResponse,
    dependencies=[Depends(ratelimit.annotations)],
)
async def get_annotations(
    content_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[ReaderContext, Depends(reader_context)],
    density: Density | None = None,
    debug: bool = False,
    refresh: bool = False,
) -> AnnotationsResponse:
    """`refresh=1`: the reader refetching after a "Know this?" answer (decision 46d), not a new
    page view: no new prompt (one per article view, DESIGN §6.5) and nothing recorded."""
    await refresh_growth()
    doc = await doc_or_error(content_id, ctx)
    density = density or ctx.density
    now = datetime.now(UTC)
    result = await score_for(ctx, doc, density, now)
    with_debug = debug and settings.env == "dev"
    items: list[AnyAnnotation] = [_annotation_out(s, with_debug) for s in result.spans]
    items += [_paragraph_out(m) for m in result.paragraphs]
    if result.preread is not None:
        items.append(_preread_out(result.preread))
    if result.prompt is not None and not refresh:
        items.append(_prompt_out(result.prompt))
    # Annotation trend (DESIGN §15.2) and today's prompt log (§6.5).
    if not refresh:
        await ReaderRepo(get_doc_store()).record_view(
            ctx.uid, doc.content_id, len(result.spans), result.prompt is not None, now
        )
    return AnnotationsResponse(
        content_id=doc.content_id,
        persona=ctx.persona,
        density=density,
        count=len(result.spans),
        annotations=items,
    )


def _paragraph_out(m: scorer.ParagraphMarker) -> ParagraphMarkerOut:
    return ParagraphMarkerOut(
        id=f"para:{m.paragraph_id}", paragraph_id=m.paragraph_id, score=round(m.score, 4),
        domain=m.domain,
    )  # fmt: skip


def _preread_out(p: scorer.Preread) -> PrereadOut:
    target = get_graph().get(p.concept_id)
    return PrereadOut(
        score=round(p.score, 4),
        concept_id=p.concept_id,
        label=target.label if target else p.concept_id,
        steps=[
            PrereadStepOut(
                concept_id=s.concept_id,
                label=s.label,
                definition=s.definition,
                content_id=s.article.content_id if s.article else None,
                title=s.article.title if s.article else None,
                known=s.known,
            )
            for s in p.steps
        ],
    )


def _prompt_out(p: scorer.UncertaintyPrompt) -> PromptOut:
    return PromptOut(
        id=f"prompt:{p.demand_id}",
        anchor=AnchorOut(**p.anchor.model_dump()),
        paragraph_id=p.paragraph_id,
        concept_id=p.concept_id,
        label=p.label,
    )


def _annotation_out(s: scorer.SpanAnnotation, with_debug: bool) -> AnnotationOut:
    return AnnotationOut(
        id=s.demand_id,
        anchor=AnchorOut(**s.anchor.model_dump()),
        paragraph_id=s.paragraph_id,
        score=round(s.score, 4),
        concept_id=s.concept_id,
        label=s.label,
        definition=s.definition,
        domain=s.domain,
        prerequisites=list(s.prerequisites),
        band=s.band,
        level=s.level,
        debug=AnnotationDebug(
            p_know=round(s.p_know, 4),
            salience=s.salience,
            span_score=round(s.score, 4),
            domain=s.domain,
            base_difficulty=s.base_difficulty,
        )
        if with_debug
        else None,
    )
