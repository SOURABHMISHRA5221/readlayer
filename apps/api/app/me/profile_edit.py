"""Edit your profile with a prompt (DESIGN §15.3; M7).

POST /v1/me/profile/edits parses the reader's description (one `profile_edit` call on MODEL_FAST,
redacted text inside content delimiters), resolves concept names through the graph linker,
and returns a preview; nothing changes until .../apply. Demo readers edit only their own
session's copy of the persona (Sourabh, 2026-10-10); POST /v1/me/demo/reset returns it to the
original. The raw text and any name the reader typed are never stored or logged.
"""

import logging
import re
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app import llm
from app.auth import Caller, current_caller
from app.config import Settings, get_settings
from app.context import scope_persona
from app.graph.loader import get_graph
from app.graph.models import DOMAINS
from app.graph.resolve import resolve_names
from app.me.router import require_consent
from app.me.topic_match import Embedder, match_topic
from app.privacy.redact import redact
from app.reader import profile_edit as pe
from app.reader.state import THINKS_IN, PersonaKey
from app.store.docstore import get_doc_store
from app.store.persona_repo import get_template
from app.store.profile_edit_repo import (
    PENDING_TTL,
    EditNotApplicable,
    EditNotFound,
    ProfileEditRepo,
)
from app.store.reader_repo import ReaderRepo
from app.store.spend_repo import today_utc

log = logging.getLogger(__name__)
router = APIRouter()
EDIT_ID = r"^[0-9a-f]{32}$"


def _repo() -> ProfileEditRepo:
    store = get_doc_store()

    async def template(persona: PersonaKey) -> dict[str, Any]:
        return await get_template(store, persona)

    return ProfileEditRepo(store, template)


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": code, "message": message}, status_code=status)


class EditIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=pe.MAX_TEXT_CHARS)


def _caps(caller: Caller, settings: Settings) -> tuple[int, str | None, int]:
    day = today_utc()
    if caller.is_anonymous:
        return (
            settings.anon_profile_edit_daily_cap,
            f"ops/profile_edit/days/{day}",
            settings.anon_global_profile_edit_daily_cap,
        )
    return settings.profile_edit_daily_cap, None, 0


@router.post("/me/profile/edits", response_model=None)
async def parse_edit(
    body: EditIn,
    caller: Annotated[Caller, Depends(current_caller)],
    settings: Annotated[Settings, Depends(get_settings)],
    persona: Annotated[PersonaKey | None, Query()] = None,
) -> dict[str, Any] | JSONResponse:
    await require_consent(caller)
    scope = scope_persona(caller, persona)
    readers = ReaderRepo(get_doc_store())
    day = today_utc()
    cap, shared, shared_cap = _caps(caller, settings)
    if not await readers.reserve_daily(
        "profile_edit_counts", caller.uid, day, cap, shared, shared_cap
    ):
        return _error(429, "profile_edit_cap", "That's enough profile edits for today.")
    await _repo().recent(caller.uid, datetime.now(UTC))  # drops expired pending edits
    graph = get_graph()
    ledger: list[llm.CallMeta] = []
    variables = {
        "text": redact(body.text),
        "domains": ", ".join(DOMAINS),
        "frames": ", ".join(THINKS_IN),
    }
    try:
        result = await llm.run_with_meta("profile_edit", pe.ModelEditOps, variables)
        ledger.append(result.meta)
        ops = pe.strict(result.output).ops
        names = pe.check_names(ops)
        topics = pe.check_topics(ops)  # before any embedding (d48)
    except llm.BudgetExceeded:
        await readers.refund_daily("profile_edit_counts", caller.uid, day, shared)
        return _error(503, "llm_budget_exceeded", "Today's AI budget is used up. Try tomorrow.")
    except ValidationError:
        return _error(422, "not_understood", "Couldn't understand that, try rephrasing.")
    except pe.EditRejected as exc:
        code = str(exc)
        message = {
            "too_many_concepts": "Too many concepts in one edit. Name at most 30.",
            "too_many_topics": (
                f"Too many topics in one edit. Name at most {pe.MAX_TOPICS_PER_EDIT}."
            ),
        }.get(code, "Couldn't understand that, try rephrasing.")
        return _error(422, code, message)
    except (llm.LLMUnavailable, llm.LLMRejected) as exc:
        if isinstance(exc.__cause__, ValidationError | ValueError):
            return _error(422, "not_understood", "Couldn't understand that, try rephrasing.")
        return _error(503, "llm_unavailable", "The AI model is unavailable. Try again shortly.")
    ids, unresolved = await resolve_names(graph, names, settings.link_threshold, ledger=ledger)
    topic_map: dict[str, str] = {}
    note: str | None = None
    topic_cost = 0.0
    if topics and scope is not None:
        note = "Feed topics are fixed in the demo."  # interest isn't modelled per persona
    elif topics:
        embedder = Embedder()
        for phrase in topics:  # one phrase per match: each reaches the embedding alone
            match = await match_topic(graph, redact(phrase), embedder, settings)
            if match is not None:
                topic_map[phrase.casefold()] = match.topic
            else:
                unresolved.append(phrase)
        topic_cost = embedder.cost
    resolved = pe.resolve(ops, ids, topic_map)
    if resolved.interests:
        # Only changes: "less" on a topic already out of the feed says nothing (d48 review).
        current = {d: s.interest for d, s in (await readers.get_domains(caller.uid)).items()}
        changing = {
            d: how
            for d, how in resolved.interests.items()
            if pe.interest_after(current.get(d, 0.0), how) != current.get(d, 0.0)
        }
        resolved = replace(resolved, interests=changing)
    touched = pe.touched(resolved, graph)
    domains = sorted(set(resolved.domains) | {c.domain for c in touched.values()})
    repo = _repo()
    edges, theta, current = await repo.state(caller.uid, scope, list(touched), domains)
    now = datetime.now(UTC)
    applied = pe.apply(resolved, graph, edges, theta, current, now)
    edit_id = uuid.uuid4().hex
    await repo.save_pending(caller.uid, edit_id, scope, resolved, now)
    log.info(
        "profile edit parsed",
        extra={
            "ops": len(ops),
            "concepts": len(resolved.concepts),
            "unresolved": len(unresolved),
            "topics": len(topic_map),
            "cost_usd": round(sum(m.cost_usd for m in ledger) + topic_cost, 6),
            "demo": scope is not None,
        },
    )
    return {
        "edit_id": edit_id,
        "persona": scope,
        "preview": pe.preview(resolved, graph, applied, theta, unresolved, note),
        "expires_in_s": int(PENDING_TTL.total_seconds()),
    }


def _summary(edit_id: str, doc: dict[str, Any]) -> dict[str, Any]:
    r = doc.get("resolved") or {}
    return {
        "edit_id": edit_id,
        "status": doc["status"],
        "persona": doc.get("persona"),
        "applied_at": doc.get("applied_at"),
        "concepts": len(r.get("concepts", {})),
        "domains": sorted(r.get("domains", {})),
        "settings": sorted(r.get("settings", {})),
        "interests": [
            {"domain": d, "direction": how} for d, how in sorted(r.get("interests", {}).items())
        ],  # fmt: skip
    }


@router.post("/me/profile/edits/{edit_id}/apply", response_model=None)
async def apply_edit(
    edit_id: str,
    caller: Annotated[Caller, Depends(current_caller)],
    persona: Annotated[PersonaKey | None, Query()] = None,
) -> dict[str, Any] | JSONResponse:
    await require_consent(caller)
    try:
        doc = await _repo().apply(
            caller.uid, scope_persona(caller, persona), _checked(edit_id), get_graph(),
            datetime.now(UTC),
        )  # fmt: skip
    except EditNotFound:
        return _error(404, "not_found", "No such edit.")
    except EditNotApplicable:
        return _error(409, "not_applicable", "This preview has expired or was already used.")
    return _summary(edit_id, doc)


@router.post("/me/profile/edits/{edit_id}/undo", response_model=None)
async def undo_edit(
    edit_id: str,
    caller: Annotated[Caller, Depends(current_caller)],
    persona: Annotated[PersonaKey | None, Query()] = None,
) -> dict[str, Any] | JSONResponse:
    await require_consent(caller)
    try:
        doc = await _repo().undo(
            caller.uid, scope_persona(caller, persona), _checked(edit_id), datetime.now(UTC)
        )
    except EditNotFound:
        return _error(404, "not_found", "No such edit.")
    except EditNotApplicable:
        return _error(409, "not_applicable", "Only an applied edit can be undone.")
    return _summary(edit_id, doc)


@router.get("/me/profile/edits")
async def list_edits(
    caller: Annotated[Caller, Depends(current_caller)],
    persona: Annotated[PersonaKey | None, Query()] = None,
) -> dict[str, Any]:
    scope = scope_persona(caller, persona)
    rows = await _repo().recent(caller.uid, datetime.now(UTC))
    return {"edits": [_summary(i, d) for i, d in rows if d.get("persona") == scope]}


class ResetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    persona: PersonaKey


@router.post("/me/demo/reset")
async def reset_demo(
    body: ResetIn, caller: Annotated[Caller, Depends(current_caller)]
) -> dict[str, Any]:
    """Back to the original persona for this demo session (the template is never changed)."""
    if not caller.is_anonymous:
        raise HTTPException(status_code=403, detail="demo readers only")
    removed = await _repo().reset_demo(caller.uid, body.persona)
    return {"reset": True, "persona": body.persona, "edits_removed": removed}


def _checked(edit_id: str) -> str:
    if not re.fullmatch(EDIT_ID, edit_id):
        raise HTTPException(status_code=404, detail="no such edit")
    return edit_id
