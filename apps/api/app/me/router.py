"""The reader's own model and data rights (DESIGN §8, §11.4, §15.2).

POST /v1/events applies interaction evidence (idempotent by event id; nothing while learning is
paused). GET/PATCH /v1/me/graph, GET /v1/me/profile and PATCH /v1/me/settings read and correct
the model; GET /v1/me/export and DELETE /v1/me are the data rights. No LLM call on any of these.
"""

from collections import Counter
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app import ratelimit
from app.auth import Caller, current_caller, forget_user, get_auth_admin
from app.context import ReaderContext, reader_context, scope_persona
from app.graph.graph import ConceptGraph
from app.graph.loader import get_graph
from app.graph.models import DOMAINS, Concept, Domain
from app.reader import model, overview, profile
from app.reader.events import ConceptRef, EventType, ReaderEvent
from app.reader.model import Band, Edge
from app.reader.personas import PERSONA_THINKS_IN
from app.reader.state import PersonaKey, ThinksIn
from app.reader.subgraph import knowledge_subgraph
from app.recs.outlets import Country
from app.store.docstore import get_doc_store
from app.store.reader_repo import Density, ExplanationStyle, ReaderRepo

router = APIRouter()

MAX_EVENTS = 100
ID_PATTERN = r"^[A-Za-z0-9_-]+$"


async def require_consent(caller: Caller) -> None:
    """Corrections and settings are records about the reader: signed-in readers consent first
    (DESIGN §11.4). Export and delete never need it, so a reader can always leave."""
    if not caller.is_anonymous and not (await _repo().get_user(caller.uid)).may_record:
        raise HTTPException(status_code=403, detail="consent_required")


def _repo() -> ReaderRepo:
    return ReaderRepo(get_doc_store())


def _ref(concept: Concept) -> ConceptRef:
    return ConceptRef(concept.domain, concept.base_difficulty)


def _band(concept: Concept, edge: Edge | None, theta: dict[str, float], now: datetime) -> Band:
    """The map's band: from evidence only. No edge → "unaware", never a prior guess (decision 69
    A); the edge's own prior stays its starting point, as in scoring."""
    if edge is None:
        return "unaware"
    p0 = model.prior(theta.get(concept.domain, 0.0), concept.base_difficulty)
    return model.band_of(model.current_p_know(edge, p0, now))


# ---------------------------------------------------------------- events


class EventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=64, pattern=ID_PATTERN)
    type: EventType
    at: datetime
    concept_id: str | None = Field(default=None, max_length=120)
    content_id: str | None = Field(default=None, max_length=120)
    paragraph_id: str | None = Field(default=None, max_length=32)
    words: int | None = Field(default=None, ge=0, le=100_000)
    ms: int | None = Field(default=None, ge=0, le=3_600_000)


class EventsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    events: list[EventIn] = Field(max_length=MAX_EVENTS)
    persona: PersonaKey | None = None  # demo persona (anonymous readers only)


class EventsResponse(BaseModel):
    applied: bool  # false while learning is paused: nothing was stored
    events_applied: int
    events_ignored: int


@router.post("/events", response_model=EventsResponse, dependencies=[Depends(ratelimit.events)])
async def post_events(
    body: EventsRequest, caller: Annotated[Caller, Depends(current_caller)]
) -> EventsResponse:
    graph = get_graph()
    refs = {
        e.concept_id: _ref(c)
        for e in body.events
        if e.concept_id and (c := graph.get(e.concept_id)) is not None
    }
    events = [
        ReaderEvent(e.id, e.type, e.at, e.concept_id, e.content_id, e.paragraph_id, e.words, e.ms)
        for e in body.events
    ]
    result = await _repo().apply_events(
        caller.uid, scope_persona(caller, body.persona), events, refs, datetime.now(UTC)
    )
    return EventsResponse(
        applied=not result.paused and not result.consent_required,
        events_applied=result.applied,
        events_ignored=result.ignored,
    )


# ---------------------------------------------------------------- graph


class EvidenceOut(BaseModel):
    type: str
    at: datetime


class GraphNodeOut(BaseModel):
    id: str
    label: str
    domain: str
    band: Band
    evidence_count: int
    last_seen: datetime | None
    depth: int
    recent: list[EvidenceOut] = []


class GraphEdgeOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    from_: str = Field(alias="from", serialization_alias="from")
    to: str


class SubgraphOut(BaseModel):
    domain: str | None
    nodes: list[GraphNodeOut]
    edges: list[GraphEdgeOut]
    truncated: bool


class ConceptBandOut(BaseModel):
    id: str
    label: str
    band: Band
    p_know: float


class DomainBandsOut(BaseModel):
    domain: str
    theta: float
    concepts: list[ConceptBandOut]


class OverviewNodeOut(BaseModel):
    id: str
    label: str
    domain: str
    band: Band
    ready: bool  # "ready to learn" ring (not known, every prerequisite known)
    goal: bool
    weight: float
    definition: str
    recent: list[EvidenceOut]
    rose_this_week: bool


class OverviewOut(BaseModel):
    """All-domains map (Design pass A5): solid known concepts and ready-to-learn rings."""

    view: Literal["overview"] = "overview"
    domains: list[str]
    nodes: list[OverviewNodeOut]
    edges: list[GraphEdgeOut]


class BandsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    concept_ids: list[Annotated[str, Field(min_length=1, max_length=120)]] = Field(max_length=50)


class GraphSummaryOut(BaseModel):
    domains: list[DomainBandsOut]
    concepts_tracked: int
    concepts_understood: int  # band "understands" or "can explain"
    trend: list[dict[str, Any]]


def _summary(
    graph: ConceptGraph, knows: dict[str, Edge], ctx: ReaderContext, weekly: dict, now: datetime
) -> GraphSummaryOut:
    theta = dict(ctx.theta)
    by_domain: dict[str, list[ConceptBandOut]] = {d: [] for d in DOMAINS}
    for cid, edge in sorted(knows.items()):
        c = graph.get(cid)
        if c is None:
            continue
        p0 = model.prior(theta.get(c.domain, 0.0), c.base_difficulty)
        p = model.current_p_know(edge, p0, now)
        by_domain[c.domain].append(ConceptBandOut(id=cid, label=c.label, band=model.band_of(p),
                                                  p_know=round(p, 4)))  # fmt: skip
    rows = [r for rs in by_domain.values() for r in rs]
    return GraphSummaryOut(
        domains=[
            DomainBandsOut(domain=d, theta=round(theta.get(d, 0.0), 4), concepts=by_domain[d])
            for d in DOMAINS
        ],
        concepts_tracked=len(rows),
        concepts_understood=sum(r.band in ("understands", "can explain") for r in rows),
        trend=_trend(weekly),
    )


def _trend(weekly: dict) -> list[dict[str, Any]]:
    return [
        {"week": w, "annotations_per_1000_words": v} for w, v in profile.annotation_trend(weekly)
    ]


@router.get("/me/graph", response_model=SubgraphOut | OverviewOut | GraphSummaryOut)
async def get_my_graph(
    ctx: Annotated[ReaderContext, Depends(reader_context)],
    domain: Domain | None = None,
    q: Annotated[str, Query(max_length=100)] = "",
    goal: Annotated[str | None, Query(pattern=r"^[0-9a-f]{12}$")] = None,
    view: Literal["overview"] | None = None,
) -> SubgraphOut | OverviewOut | GraphSummaryOut:
    graph = get_graph()
    now = datetime.now(UTC)
    if view == "overview":
        return await _overview(ctx, now)
    repo = _repo()
    knows = dict(ctx.state.edges)
    exact: list[str] | None = None
    if goal is not None:  # a learning goal's targets only (M7.5 §C.5)
        from app.me.goals import goal_target_ids

        exact = None if ctx.caller.is_anonymous else await goal_target_ids(ctx.uid, goal)
        if exact is None:
            raise HTTPException(status_code=404, detail="goal not found")
    if exact is None and domain is None and not q.strip():
        return _summary(graph, knows, ctx, await repo.get_weekly(ctx.uid), now)
    theta = dict(ctx.theta)
    sub = knowledge_subgraph(
        graph, knows, lambda c: _band(c, knows.get(c.id), theta, now), now, domain, q, exact
    )
    return SubgraphOut(
        domain=domain,
        nodes=[
            GraphNodeOut(**(vars(n) | {"recent": [EvidenceOut(type=k, at=a) for k, a in n.recent]}))
            for n in sub.nodes
        ],
        edges=[GraphEdgeOut(from_=a, to=b) for a, b in sub.edges],
        truncated=sub.truncated,
    )


async def _overview(ctx: ReaderContext, now: datetime) -> OverviewOut:
    from app.me.goals import targets_for_feed

    goal_ids = [] if ctx.caller.is_anonymous else list(await targets_for_feed(ctx.uid))
    interest = {d: s.interest for d, s in ctx.domains.items()}
    ov = overview.build(get_graph(), ctx.state, interest, goal_ids, now)
    return OverviewOut(
        domains=list(ov.domains),
        nodes=[
            OverviewNodeOut(
                **(vars(n) | {"recent": [EvidenceOut(type=k, at=a) for k, a in n.recent]})
            )
            for n in ov.nodes
        ],
        edges=[GraphEdgeOut(from_=a, to=b) for a, b in ov.edges],
    )


@router.post("/me/bands", response_model=dict[str, Band])
async def my_bands(
    body: BandsIn, ctx: Annotated[ReaderContext, Depends(reader_context)]
) -> dict[str, Band]:
    """Current bands for the recap (Design pass A4): the same uncapped band explanations use.
    Unknown ids are left out. A pure read."""
    graph, now = get_graph(), datetime.now(UTC)
    return {
        cid: model.band_of(overview.p_know(c, ctx.state, now))
        for cid in dict.fromkeys(body.concept_ids)
        if (c := graph.get(cid)) is not None
    }


class CorrectionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: Literal["known", "unknown"]


class CorrectionOut(BaseModel):
    concept_id: str
    band: Band
    p_know: float


@router.patch("/me/graph/{concept_id}", response_model=CorrectionOut)
async def correct_concept(
    concept_id: str,
    body: CorrectionIn,
    caller: Annotated[Caller, Depends(current_caller)],
    persona: Annotated[PersonaKey | None, Query()] = None,
) -> CorrectionOut:
    """ "I know this" / "I don't": strong evidence, applied even while learning is paused."""
    await require_consent(caller)
    concept = get_graph().get(concept_id)
    if concept is None:
        raise HTTPException(status_code=404, detail="concept not found")
    edge = await _repo().correct(
        caller.uid,
        scope_persona(caller, persona),
        concept_id,
        _ref(concept),
        body.state == "known",
        datetime.now(UTC),
    )
    return CorrectionOut(concept_id=concept_id, band=edge.band, p_know=round(model.p_know(edge), 4))


# ---------------------------------------------------------------- profile and settings


def _domain_of(graph: ConceptGraph, cid: str) -> str | None:
    c = graph.get(cid)
    return c.domain if c is not None else None


@router.get("/me/profile")
async def get_profile(ctx: Annotated[ReaderContext, Depends(reader_context)]) -> dict[str, Any]:
    """Deterministic (DESIGN §15.1): no LLM call anywhere on this path."""
    graph = get_graph()
    now = datetime.now(UTC)
    user = ctx.user
    domains = ctx.domains
    knows = dict(ctx.state.edges)
    weekly = await _repo().get_weekly(ctx.uid)
    theta = {d: float(ctx.theta.get(d, 0.0)) for d in DOMAINS}
    # A domain whose level was set or moved (`profile.rated_domains`): the summary and the level
    # words speak only about those. A neutral 0 with only recorded ideas (home terms) isn't
    # "comfortable" (decision 69 A2).
    rated = profile.rated_domains(
        theta, user.onboarding.get("comfort", {}), knows, lambda cid: _domain_of(graph, cid)
    ) & set(DOMAINS)
    moves = [m for m in profile.moved_up_this_week(knows, now) if graph.get(m.concept_id)]
    in_graph = Counter(c.domain for c in graph.concepts)  # the map offers domains with concepts
    # Ideas the reader has shown they know (an edge at "understands" or above), per domain.
    known = Counter(
        c.domain for cid, e in knows.items()
        if e.band in ("understands", "can explain") and (c := graph.get(cid)) is not None
    )  # fmt: skip
    # A demo reader's frame is the persona's, the one explanations use (not users/{uid}).
    frames = (
        list(ctx.state.thinks_in or [PERSONA_THINKS_IN[ctx.persona]])
        if ctx.persona
        else list(user.thinks_in)
    )
    return {
        "summary": {
            "text": profile.summary_text({d: theta[d] for d in rated}, frames, len(moves)),
            "top_domain": profile.top_domain({d: theta[d] for d in rated}),
            "moved_up_this_week": len(moves),
            "learning_paused": user.learning_paused,
        },
        "domains": [
            {
                "domain": d,
                "theta": round(theta[d], 4),
                "rated": d in rated,
                "interest": domains[d].interest if d in domains else 0.0,
                "thinks_in": domains[d].thinks_in if d in domains else 0.0,
                "concepts": in_graph[d],
                "known": known[d],
            }
            for d in DOMAINS
        ],
        "thinks_in": frames,
        "week": {
            "moved_up": [
                {
                    "concept_id": m.concept_id,
                    "label": graph.get(m.concept_id).label,  # type: ignore[union-attr]
                    "domain": graph.get(m.concept_id).domain,  # type: ignore[union-attr]
                    "from": m.from_band,
                    "to": m.to_band,
                }
                for m in moves
            ],
            "trend": _trend(weekly),
        },
        "settings": {
            "density": user.density,
            "explanation_style": user.explanation_style,
            # Decision 50; demo readers have none (they read as PERSONA_COUNTRY).
            "country": None if ctx.caller.is_anonymous else user.country,
        },
        "persona": ctx.persona,
        "onboarding": {
            "consented": user.may_record,
            "done": ctx.caller.is_anonymous or user.onboarding_done,
            "step": _onboarding_step(ctx.caller.is_anonymous, user),
            # Screen 2 resumes and Edit refills screen 1 from these (decision 41).
            "field": user.field,
            "interests": list(user.onboarding.get("interests", [])),
            "formats": [] if ctx.caller.is_anonymous else list(user.formats),
            "redo": user.onboarding_redo,
            "consent_version": (user.consent or {}).get("version"),
        },
    }


def _onboarding_step(anonymous: bool, user: Any) -> str:
    if anonymous or user.onboarding_done:
        return "done"
    if user.consent is None:
        return "consent"
    # After POST /v1/onboarding the reader is on screen 2 until POST /v1/onboarding/finish.
    return "discover" if user.field else "onboarding"


class SettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    thinks_in: list[ThinksIn] | None = Field(default=None, max_length=3)
    density: Density | None = None
    explanation_style: ExplanationStyle | None = None
    learning_paused: bool | None = None
    country: Country | None = None  # decision 50; "other" is the way to say "not these"


@router.patch("/me/settings")
async def patch_settings(
    body: SettingsIn, caller: Annotated[Caller, Depends(current_caller)]
) -> dict[str, Any]:
    await require_consent(caller)
    changes = body.model_dump(exclude_none=True)
    if "country" in changes and caller.is_anonymous:  # demo readers read as PERSONA_COUNTRY
        raise HTTPException(status_code=403, detail="country_needs_sign_in")
    if "thinks_in" in changes:
        changes["thinks_in"] = sorted(set(changes["thinks_in"]))
    user = await _repo().update_settings(caller.uid, changes)
    return {
        "thinks_in": user.thinks_in,
        "density": user.density,
        "explanation_style": user.explanation_style,
        "learning_paused": user.learning_paused,
        "country": user.country,
    }


# ---------------------------------------------------------------- data rights


@router.get("/me/export")
async def export_me(caller: Annotated[Caller, Depends(current_caller)]) -> JSONResponse:
    data = await _repo().export(caller.uid)
    data["exported_at"] = datetime.now(UTC)
    return JSONResponse(
        jsonable_encoder(data),
        headers={"Content-Disposition": 'attachment; filename="readlayer-export.json"'},
    )


@router.delete("/me", status_code=204)
async def delete_me(caller: Annotated[Caller, Depends(current_caller)]) -> Response:
    """Every document under users/{uid}, then the Firebase Auth user. Safe to retry."""
    await _repo().delete(caller.uid)
    forget_user(caller.uid, deleted=True)
    await get_auth_admin().delete_user(caller.uid)
    return Response(status_code=204)
