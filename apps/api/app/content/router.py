"""Read side of content for the reader UI: library list, article body, annotations.

Annotations come from the PLACEHOLDER scorer (app/scoring/placeholder.py) until M4.
"""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.auth import current_uid
from app.config import Settings, get_settings
from app.content.summary import article_domain
from app.graph.loader import get_graph
from app.ingest.models import ContentDoc
from app.scoring import placeholder
from app.scoring.placeholder import DENSITY_THRESHOLDS, PERSONAS, Density, PersonaKey
from app.store.content_repo import get_content_store

router = APIRouter(dependencies=[Depends(current_uid)])

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
    persona: PersonaKey
    density: Density
    count: int
    annotations: list[AnnotationOut]


# Every stored doc, loaded once per process (dev slice; ~300 docs). Library rows per
# (persona, density) are pure computation over these and cached alongside.
_docs: list[ContentDoc] | None = None
_rows: dict[tuple[PersonaKey, Density], list[ContentSummary]] = {}
_lock = asyncio.Lock()


def reset_catalog() -> None:
    global _docs
    _docs = None
    _rows.clear()


async def _summaries(persona: PersonaKey, density: Density) -> list[ContentSummary]:
    global _docs
    async with _lock:
        if _docs is None:
            docs = [doc async for doc in get_content_store().iter_all()]
            _docs = sorted(docs, key=lambda d: (d.title.casefold(), d.content_id))
            _rows.clear()
        key = (persona, density)
        if key not in _rows:
            graph = get_graph()
            theta, threshold = PERSONAS[persona].theta, DENSITY_THRESHOLDS[density]
            _rows[key] = [
                _summary(
                    d,
                    article_domain(d, graph),
                    len(placeholder.annotate(d, graph, theta, threshold)),
                )
                for d in _docs
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
    q: Annotated[str, Query(max_length=MAX_QUERY_CHARS)] = "",
    persona: PersonaKey = "newcomer",
    density: Density = "balanced",
) -> list[ContentSummary]:
    needle = q.strip().casefold()
    items = await _summaries(persona, density)
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


@router.get("/content/{content_id}/annotations", response_model=AnnotationsResponse)
async def get_annotations(
    content_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
    persona: PersonaKey = "newcomer",
    density: Density = "balanced",
    debug: bool = False,
) -> AnnotationsResponse:
    doc = await _doc_or_404(content_id)
    spans = placeholder.annotate(
        doc, get_graph(), PERSONAS[persona].theta, DENSITY_THRESHOLDS[density]
    )
    with_debug = debug and settings.env == "dev"
    items = [_annotation_out(s, with_debug) for s in spans]
    return AnnotationsResponse(
        content_id=doc.content_id,
        persona=persona,
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
