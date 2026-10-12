"""POST /v1/explain and POST /v1/explain/{id}/report (DESIGN §7, §8).

The reader's band, frame and style are computed here from their own state; the prompt gets
only content plus those three (app/explain/inputs.py). The annotations route stays LLM-free:
the web client prefetches its top spans through this endpoint after the annotations load.
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Annotated, Literal, cast

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app import ratelimit
from app.auth import Caller, current_caller
from app.config import Settings, get_settings
from app.content.access import require_readable
from app.context import ReaderContext, reader_context, scope_persona
from app.explain import service
from app.explain.inputs import ExplainInputs, paragraph_inputs, span_inputs
from app.explain.models import Mode
from app.graph.loader import get_graph
from app.reader.events import ConceptRef, ReaderEvent
from app.reader.model import BANDS, Band
from app.reader.personas import PERSONA_THINKS_IN
from app.reader.state import THINKS_IN, ExplanationStyle, PersonaKey, ThinksIn
from app.store.content_repo import get_content_store
from app.store.docstore import get_doc_store
from app.store.explain_repo import ExplainRepo
from app.store.reader_repo import ReaderRepo
from app.store.spend_repo import today_utc

log = logging.getLogger(__name__)
router = APIRouter()

ID_PATTERN = r"^[A-Za-z0-9_-]+$"
# A card id names its two cache entries (restatement-background); a bare key is still accepted.
KEY_PATTERN = r"^[0-9a-f]{40}(-[0-9a-f]{40})?$"


class ExplainRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_id: str = Field(min_length=1, max_length=120, pattern=ID_PATTERN)
    demand_id: str | None = Field(default=None, min_length=1, max_length=32, pattern=ID_PATTERN)
    paragraph_id: str | None = Field(default=None, min_length=1, max_length=32, pattern=ID_PATTERN)
    # "Say it simpler" (-1) / "Go deeper" (+1): the Background one band from the reader's own,
    # through the same verified path and cache (keyed by band). Span mode only. Design pass A3.
    shift: Literal[-1, 0, 1] = 0

    @model_validator(mode="after")
    def _one_target(self) -> "ExplainRequest":
        if (self.demand_id is None) == (self.paragraph_id is None):
            raise ValueError("give exactly one of demand_id or paragraph_id")
        if self.shift and self.paragraph_id is not None:
            raise ValueError("shift applies to span notes only")
        return self


class ExplainResponse(BaseModel):
    id: str  # cache key; the report action names it
    kind: Literal["verified", "definition"]
    mode: Mode
    label: str
    definition: str  # always present: the fallback card and the instant content
    concept_id: str | None
    background: str | None
    author_says: str | None
    analogy_domain: ThinksIn | None
    band: Band  # the band this Background was written for (the reader's own, or shifted)
    can_simpler: bool  # a band below the reader's own exists (span notes only)
    can_deeper: bool
    thinks_in: ThinksIn | None
    style: ExplanationStyle
    cached: bool
    capped: bool = (
        False  # the daily explain cap stopped a generation (definition or shared part only)
    )
    prompt_version: str


class ReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1, max_length=64, pattern=ID_PATTERN)
    content_id: str = Field(min_length=1, max_length=120, pattern=ID_PATTERN)
    concept_id: str | None = Field(default=None, max_length=120)
    paragraph_id: str | None = Field(default=None, max_length=32)


class ReportResponse(BaseModel):
    evicted: bool  # false if the entry was already gone
    event_applied: bool


def frame_for(ctx: ReaderContext) -> ThinksIn | None:
    """Demo personas have a fixed frame (unless this demo session changed it with a profile
    edit); signed-in readers their first THINKS_IN choice."""
    if ctx.persona is not None:
        session = [f for f in ctx.state.thinks_in if f in THINKS_IN]
        return cast(ThinksIn, session[0]) if session else PERSONA_THINKS_IN[ctx.persona]
    frames = [f for f in ctx.user.thinks_in if f in THINKS_IN]
    return cast(ThinksIn, frames[0]) if frames else None


def shifted(band: Band, shift: int) -> Band:
    """One band lower or higher, clamped to the four bands."""
    return BANDS[max(0, min(len(BANDS) - 1, BANDS.index(band) + shift))]


async def _inputs(body: ExplainRequest, ctx: ReaderContext, now: datetime) -> ExplainInputs:
    doc = await get_content_store().get(body.content_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="content not found")
    await require_readable(doc, ctx.uid, ctx.ingested)
    frame, style = frame_for(ctx), ctx.user.explanation_style
    if body.paragraph_id is not None:
        inputs = paragraph_inputs(doc, body.paragraph_id, get_graph(), ctx.state, frame, style)
        if inputs is None:
            raise HTTPException(status_code=404, detail="paragraph not found")
        return inputs
    demand = next((d for d in doc.demands if d.id == body.demand_id), None)
    if demand is None:
        raise HTTPException(status_code=404, detail="annotation not found")
    inputs = span_inputs(doc, demand, get_graph(), ctx.state, now, frame, style)
    if inputs is None:
        raise HTTPException(status_code=422, detail="this phrase has no glossary entry")
    return inputs


Quota = tuple[Callable[[], Awaitable[bool]], Callable[[], Awaitable[None]]]


def _quota(ctx: ReaderContext, settings: Settings) -> Quota:
    """Reserve / refund one uncached generation against the reader's daily cap (and the
    shared anonymous cap, kept in the ops/explain day doc as `anonymous`)."""
    repo = ReaderRepo(get_doc_store())
    day = today_utc()
    anon = ctx.caller.is_anonymous
    shared = f"ops/explain/days/{day}" if anon else None
    cap = settings.anon_explain_daily_cap if anon else settings.explain_daily_cap
    cap_all = settings.anon_global_explain_daily_cap

    async def reserve() -> bool:
        return await repo.reserve_daily("explain_counts", ctx.uid, day, cap, shared, cap_all)

    async def refund() -> None:
        await repo.refund_daily("explain_counts", ctx.uid, day, shared)

    return reserve, refund


@router.post("/explain", response_model=ExplainResponse, dependencies=[Depends(ratelimit.explain)])
async def explain(
    body: ExplainRequest,
    tasks: BackgroundTasks,
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[ReaderContext, Depends(reader_context)],
) -> ExplainResponse:
    timer = service.Timer()
    base = await _inputs(body, ctx, datetime.now(UTC))
    own = BANDS.index(base.band)  # the reader's own band; a shift moves only the Background's
    inputs = replace(base, band=shifted(base.band, body.shift)) if body.shift else base
    repo = ExplainRepo(get_doc_store())
    reserve, refund = _quota(ctx, settings)
    served = await service.serve(inputs, repo, reserve=reserve, refund=refund)
    ms = timer.ms()
    service.record_latency(served.cached, ms)
    log.info(
        "explain",
        extra={
            "cache": "hit" if served.cached else "miss",
            "kind": served.kind,
            "reason": served.reason,
            "mode": inputs.mode,
            "latency_ms": ms,
            "cost_usd": served.cost_usd,
        },
    )
    if served.counts:
        tasks.add_task(repo.count, today_utc(), served.counts)
    e = served.explanation
    return ExplainResponse(
        id=served.key,
        kind=served.kind,
        mode=inputs.mode,
        label=inputs.label,
        definition=inputs.definition,
        concept_id=inputs.concept_id,
        background=e.background if e else None,
        author_says=e.author_says if e else None,
        analogy_domain=e.analogy_domain if e else None,
        band=inputs.band,
        can_simpler=inputs.mode == "span" and own > 0,
        can_deeper=inputs.mode == "span" and own < len(BANDS) - 1,
        thinks_in=inputs.thinks_in,
        style=inputs.style,
        cached=served.cached,
        capped=served.reason == "capped",
        prompt_version=service.prompt_version(),
    )


@router.post(
    "/explain/{key}/report",
    response_model=ReportResponse,
    dependencies=[Depends(ratelimit.events)],
)
async def report_wrong(
    key: Annotated[str, Path(pattern=KEY_PATTERN)],
    body: ReportRequest,
    tasks: BackgroundTasks,
    caller: Annotated[Caller, Depends(current_caller)],
    persona: Annotated[PersonaKey | None, Query()] = None,
) -> ReportResponse:
    """ "This is wrong": evict the entry for everyone, queue it for review, and record a
    report_wrong event. Eviction happens even while learning is paused (it is about the
    content, not the reader); the event follows the pause rule like every other event."""
    now = datetime.now(UTC)
    repo = ExplainRepo(get_doc_store())
    # Both parts go: the shared restatement for everyone, and this reader's Background.
    evicted = False
    for part in service.split_card_id(key):
        evicted |= await repo.evict_to_review(part, f"{part[:16]}-{body.event_id}", now)
    concept = get_graph().get(body.concept_id) if body.concept_id else None
    refs = {concept.id: ConceptRef(concept.domain, concept.base_difficulty)} if concept else {}
    event = ReaderEvent(
        body.event_id, "report_wrong", now, concept.id if concept else None, body.content_id,
        body.paragraph_id,
    )  # fmt: skip
    result = await ReaderRepo(get_doc_store()).apply_events(
        caller.uid, scope_persona(caller, persona), [event], refs, now
    )
    if evicted:
        tasks.add_task(repo.count, today_utc(), {"reports": 1})
    log.info("explanation reported", extra={"evicted": evicted, "event_applied": result.applied})
    return ReportResponse(evicted=evicted, event_applied=result.applied > 0)
