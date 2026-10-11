"""Reading goals (M7.5 §C, DESIGN §18): GET/POST/DELETE /v1/me/goals.

Signed-in readers only (demo readers get 403), after consent, at most 5 goals:
- habit: articles or minutes per week, counted from this ISO week's reading (`weekly`);
- learning: "understand X". The text is redacted, its leading verb stripped, and X resolved
  through `resolve_names` (exact match, then embedding candidates + link_confirm). Only the
  resolved target ids and labels are stored — never the raw or redacted text — and logs carry
  the outcome and cost only. Targets are the concept plus its prerequisite chain (≤ 8).
Progress is computed on read, with no LLM.
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app import llm
from app.auth import Caller, current_caller
from app.config import Settings, get_settings
from app.context import ReaderContext, reader_context
from app.graph.loader import get_graph
from app.graph.models import Concept, Domain
from app.graph.resolve import resolve_names
from app.graph.taxonomy import BY_ID
from app.me.router import require_consent
from app.me.topic_match import Embedder, match_topic
from app.privacy.redact import redact
from app.reader import goals as g
from app.reader import onboarding_text as ot
from app.reader.profile import iso_week
from app.store.docstore import get_doc_store
from app.store.reader_repo import ReaderRepo, sub_path, user_path
from app.store.spend_repo import today_utc

log = logging.getLogger("app.me.goals")
GOAL_ID = r"^[0-9a-f]{12}$"  # uuid4().hex[:12]; never a path separator
router = APIRouter()


class HabitIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["habit"]
    metric: g.Metric
    per_week: int = Field(ge=1, le=600)


class LearningIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["learning"]
    text: str = Field(min_length=2, max_length=120)


class ResolvedIn(BaseModel):
    """A goal the reader saw in preview (decision 48): ids only, re-validated against the graph;
    no model call and no cap charge."""

    model_config = ConfigDict(extra="forbid")
    type: Literal["learning_resolved"]
    kind: Literal["concept", "topic"]
    concept_id: str | None = Field(default=None, max_length=120, pattern=r"^[a-z0-9_]+$")
    topic: Domain | None = None
    target_ids: list[Annotated[str, Field(max_length=120, pattern=r"^[a-z0-9_]+$")]] = Field(
        min_length=1, max_length=g.TOPIC_TARGETS
    )


class TargetOut(BaseModel):
    concept_id: str
    label: str
    known: bool


class GoalOut(BaseModel):
    id: str
    type: Literal["habit", "learning"]
    kind: Literal["concept", "topic"] | None = None
    label: str
    metric: g.Metric | None = None
    per_week: int | None = None
    targets: list[TargetOut] = []
    done: float
    total: float
    fraction: float
    paused: bool = False


def _repo() -> ReaderRepo:
    return ReaderRepo(get_doc_store())


def _signed_in(caller: Caller) -> None:
    if caller.is_anonymous:
        raise HTTPException(status_code=403, detail="goals_signed_in_only")


async def _goals(uid: str) -> list[tuple[str, dict[str, Any]]]:
    return await get_doc_store().list(f"{user_path(uid)}/goals")


async def targets_for_feed(uid: str) -> dict[str, str]:
    """Learning-goal target concept id → the goal's label, for the feed's goal boost."""
    out: dict[str, str] = {}
    for _, doc in await _goals(uid):
        if doc.get("type") == "learning":
            for t in doc.get("targets", []):
                out.setdefault(t["concept_id"], doc["label"])
    return out


def _habit_bounds(metric: str, per_week: int) -> bool:
    return 1 <= per_week <= 50 if metric == "articles" else 10 <= per_week <= 600


async def _out(goal_id: str, doc: dict[str, Any], ctx: ReaderContext, weekly: dict) -> GoalOut:
    now = datetime.now(UTC)
    if doc["type"] == "habit":
        p = g.habit_progress(doc["metric"], doc["per_week"], weekly.get(iso_week(now)),
                             ctx.user.learning_paused)  # fmt: skip
        label = f"{doc['per_week']} {doc['metric']} a week"
        return GoalOut(id=goal_id, type="habit", label=label, metric=doc["metric"],
                       per_week=doc["per_week"], done=p.done, total=p.total,
                       fraction=round(p.fraction, 3), paused=p.paused)  # fmt: skip
    graph = get_graph()
    ids = [t["concept_id"] for t in doc.get("targets", [])]
    p = g.learning_progress(graph, ids, ctx.state, now)
    targets = [
        TargetOut(concept_id=t["concept_id"], label=t["label"],
                  known=bool((c := graph.get(t["concept_id"])) and g.is_known(c, ctx.state, now)))
        for t in doc.get("targets", [])
    ]  # fmt: skip
    return GoalOut(id=goal_id, type="learning", kind=doc.get("kind", "concept"),
                   label=doc["label"], targets=targets, done=p.done, total=p.total,
                   fraction=round(p.fraction, 3))  # fmt: skip


@router.get("/me/goals", response_model=list[GoalOut])
async def list_goals(ctx: Annotated[ReaderContext, Depends(reader_context)]) -> list[GoalOut]:
    _signed_in(ctx.caller)
    weekly = await _repo().get_weekly(ctx.uid)
    return [await _out(gid, doc, ctx, weekly) for gid, doc in sorted(await _goals(ctx.uid))]


@router.post("/me/goals/preview", response_model=None, responses={422: {}, 429: {}})
async def preview_goal(
    body: LearningIn,
    ctx: Annotated[ReaderContext, Depends(reader_context)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any] | JSONResponse:
    """What "understand X" resolves to (a concept, or a topic and its ideas). Nothing written;
    the resolve is charged here, and saving the previewed ids costs nothing."""
    _signed_in(ctx.caller)
    await require_consent(ctx.caller)
    return await _resolve(ctx.caller, body.text, settings)


@router.post("/me/goals", response_model=GoalOut, responses={422: {}, 429: {}})
async def create_goal(
    body: HabitIn | LearningIn | ResolvedIn,
    ctx: Annotated[ReaderContext, Depends(reader_context)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> GoalOut | JSONResponse:
    _signed_in(ctx.caller)
    await require_consent(ctx.caller)
    if len(await _goals(ctx.uid)) >= g.MAX_GOALS:
        return _error(409, "too_many_goals", f"You can keep up to {g.MAX_GOALS} goals.")
    goal_id = uuid.uuid4().hex[:12]
    if isinstance(body, HabitIn):
        if not _habit_bounds(body.metric, body.per_week):
            return _error(422, "bad_habit", "Pick 1–50 articles or 10–600 minutes a week.")
        doc: dict[str, Any] = {"type": "habit", "metric": body.metric, "per_week": body.per_week}
    elif isinstance(body, ResolvedIn):
        checked = _checked(body)
        if isinstance(checked, JSONResponse):
            return checked
        doc = checked
    else:
        resolved = await _resolve(ctx.caller, body.text, settings)
        if isinstance(resolved, JSONResponse):
            return resolved
        doc = resolved
    doc["created_at"] = datetime.now(UTC).isoformat()

    async def write(t):
        t.set(sub_path(ctx.uid, "goals", goal_id), doc)

    await get_doc_store().run(write)
    return await _out(goal_id, doc, ctx, await _repo().get_weekly(ctx.uid))


async def _resolve(caller: Caller, text: str, settings: Settings) -> dict[str, Any] | JSONResponse:
    """Decision 48 order, one phrase, embedded at most once: exact concept → whole-phrase topic
    alias (no model call) → `resolve_names` (embedding candidates + link_confirm) → words and
    2-word chunks → nearest topic by embedding. The text is never stored or logged."""
    ok = await _repo().reserve_daily(
        "goal_resolve_counts", caller.uid, today_utc(), settings.goal_resolve_daily_cap, None, 0
    )
    if not ok:
        return _error(429, "goal_cap_reached", "That's enough new goals for today. Try tomorrow.")
    phrase = g.strip_prefix(redact(text))
    graph = get_graph()
    ledger: list[llm.CallMeta] = []
    embedder = Embedder()
    concept = graph.lookup(phrase)
    topic = None if concept is not None else ot.alias_topic(phrase)
    if concept is None and topic is None:
        ids, _ = await resolve_names(graph, [phrase], settings.link_threshold, embed=embedder,
                                     ledger=ledger)  # fmt: skip
        cid = ids.get(phrase.casefold())
        concept = graph.get(cid) if cid else None
    if concept is None and topic is None:
        match = await match_topic(graph, phrase, embedder, settings)
        topic = match.topic if match else None
    cost = round(embedder.cost + sum(m.cost_usd for m in ledger), 6)
    outcome = "concept" if concept else "topic" if topic else "not_found"
    log.info("goal resolve", extra={"outcome": outcome, "cost_usd": cost})
    if concept is not None:
        found = g.targets(graph, concept.id)
        return _draft("concept", concept.label, found, concept_id=concept.id)
    if topic is not None:
        found = g.topic_targets(graph, topic, phrase)
        if found:
            return _draft("topic", BY_ID[topic].label, found, topic=topic)
    return _error(422, "goal_not_found", "We couldn't find that idea yet. Try another name.")


def _draft(kind: str, label: str, found: list[Concept], *, concept_id: str | None = None,
           topic: str | None = None) -> dict[str, Any]:  # fmt: skip
    """A goal ready to store and to preview: ids and graph labels only."""
    return {"type": "learning", "kind": kind, "label": label, "concept_id": concept_id,
            "topic": topic,
            "targets": [{"concept_id": c.id, "label": c.label} for c in found]}  # fmt: skip


def _checked(body: ResolvedIn) -> dict[str, Any] | JSONResponse:
    """A previewed goal, re-derived from the graph: a concept goal's targets must be exactly its
    chain; a topic goal's ids must all exist and sit in that topic."""
    graph = get_graph()
    bad = _error(422, "goal_not_valid", "That goal no longer matches. Preview it again.")
    if body.kind == "concept":
        concept = graph.get(body.concept_id or "")
        if concept is None:
            return bad
        found = g.targets(graph, concept.id)
        if [c.id for c in found] != body.target_ids:
            return bad
        return _draft("concept", concept.label, found, concept_id=concept.id)
    if body.topic is None:
        return bad
    found = [c for cid in dict.fromkeys(body.target_ids) if (c := graph.get(cid)) is not None]
    if len(found) != len(set(body.target_ids)) or any(c.domain != body.topic for c in found):
        return bad
    return _draft("topic", BY_ID[body.topic].label, found, topic=body.topic)


@router.delete("/me/goals/{goal_id}", status_code=204)
async def delete_goal(
    goal_id: Annotated[str, Path(pattern=GOAL_ID)],
    caller: Annotated[Caller, Depends(current_caller)],
) -> None:
    _signed_in(caller)

    async def body(t):
        t.delete(sub_path(caller.uid, "goals", goal_id))

    await get_doc_store().run(body)


async def goal_target_ids(uid: str, goal_id: str) -> list[str] | None:
    doc = await get_doc_store().get(sub_path(uid, "goals", goal_id))
    if not doc or doc.get("type") != "learning":
        return None
    return [t["concept_id"] for t in doc.get("targets", [])]


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": code, "message": message}, status_code=status)
