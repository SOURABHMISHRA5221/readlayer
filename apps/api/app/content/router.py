"""Read side of content for the reader UI: library list, article body, annotations.

Annotations come from the PLACEHOLDER scorer (app/scoring/placeholder.py) until M4.
"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app import ratelimit
from app.config import Settings, get_settings
from app.content import catalog
from app.content.summary import article_domain
from app.context import ReaderContext, reader_context
from app.graph.loader import get_graph
from app.ingest.models import ContentDoc
from app.scoring import placeholder
from app.scoring.placeholder import DENSITY_THRESHOLDS, Density, PersonaKey
from app.store.content_repo import get_content_store
from app.store.docstore import get_doc_store
from app.store.reader_repo import ReaderRepo

router = APIRouter()

MAX_QUERY_CHARS = 200


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


class ParagraphOut(BaseModel):
    id: str
    text: str


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
    kind: str = "span"
    anchor: AnchorOut
    paragraph_id: str
    score: float
    concept_id: str
    label: str
    definition: str
    domain: str
    prerequisites: list[str]
    debug: AnnotationDebug | None = None


class AnnotationsResponse(BaseModel):
    content_id: str
    persona: PersonaKey | None  # demo persona; None for a signed-in reader
    density: Density
    count: int
    annotations: list[AnnotationOut]


# Library rows per (catalog version, reader view, density): pure computation over the shared
# catalog, cached because the list endpoint is hit on every library view. Bounded: signed-in
# readers each have their own θ, so keys can grow with readers.
_rows: dict[tuple[int, str, Density], list[ContentSummary]] = {}
MAX_CACHED_VIEWS = 64


def reset_catalog() -> None:
    catalog.reset()
    _rows.clear()


async def _summaries(ctx: ReaderContext, density: Density) -> list[ContentSummary]:
    docs = await catalog.all_docs()
    key = (catalog.version(), ctx.view_key, density)
    if key not in _rows:
        graph = get_graph()
        theta, threshold = ctx.theta, DENSITY_THRESHOLDS[density]
        if len(_rows) >= MAX_CACHED_VIEWS:
            _rows.pop(next(iter(_rows)))
        _rows[key] = [
            _summary(
                d, article_domain(d, graph), len(placeholder.annotate(d, graph, theta, threshold))
            )
            for d in docs
        ]
    return _rows[key]


def _summary(doc: ContentDoc, domain: str | None, concepts_new: int) -> ContentSummary:
    return ContentSummary(
        id=doc.content_id,
        title=doc.title,
        site=doc.site,
        word_count=placeholder.word_count(doc),
        description=doc.description,
        author=doc.author,
        published=doc.published,
        image=doc.image,
        domain=domain,
        concepts_new=concepts_new,
    )


async def _doc_or_404(content_id: str) -> ContentDoc:
    doc = await get_content_store().get(content_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="content not found")
    return doc


@router.get("/content", response_model=list[ContentSummary])
async def list_content(
    ctx: Annotated[ReaderContext, Depends(reader_context)],
    q: Annotated[str, Query(max_length=MAX_QUERY_CHARS)] = "",
    density: Density = "balanced",
) -> list[ContentSummary]:
    needle = q.strip().casefold()
    items = await _summaries(ctx, density)
    if not needle:
        return items
    return [s for s in items if needle in s.title.casefold() or needle in s.site.casefold()]


@router.get("/content/{content_id}", response_model=ContentDetail)
async def get_content(content_id: str) -> ContentDetail:
    doc = await _doc_or_404(content_id)
    return ContentDetail(
        id=doc.content_id,
        title=doc.title,
        site=doc.site,
        url=doc.final_url or doc.url,
        word_count=placeholder.word_count(doc),
        description=doc.description,
        author=doc.author,
        published=doc.published,
        image=doc.image,
        domain=article_domain(doc, get_graph()),
        paragraphs=[ParagraphOut(id=p.id, text=p.text) for p in doc.paragraphs],
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
    density: Density = "balanced",
    debug: bool = False,
) -> AnnotationsResponse:
    doc = await _doc_or_404(content_id)
    spans = placeholder.annotate(doc, get_graph(), ctx.theta, DENSITY_THRESHOLDS[density])
    with_debug = debug and settings.env == "dev"
    items = [_annotation_out(s, with_debug) for s in spans]
    # Annotation trend (DESIGN §15.2): once per content per week, skipped while paused.
    await ReaderRepo(get_doc_store()).record_annotations_shown(
        ctx.uid, doc.content_id, len(items), datetime.now(UTC)
    )
    return AnnotationsResponse(
        content_id=doc.content_id,
        persona=ctx.persona,
        density=density,
        count=len(items),
        annotations=items,
    )


def _annotation_out(s: placeholder.SpanAnnotation, with_debug: bool) -> AnnotationOut:
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
