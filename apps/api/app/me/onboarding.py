"""Consent, onboarding and calibration for signed-in (Google) readers (DESIGN §4, §8, §11.4; M7).

Demo (anonymous) readers never come here: they read as a persona. No LLM call on any route.
"""

from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.auth import Caller, current_caller
from app.graph.loader import get_graph
from app.graph.models import DOMAINS, Domain
from app.reader import onboarding
from app.reader.events import ConceptRef
from app.reader.onboarding import Answer, Level
from app.reader.state import ThinksIn
from app.recs.models import Format
from app.recs.outlets import Country
from app.store.content_repo import get_content_store
from app.store.docstore import get_doc_store
from app.store.reader_repo import ReaderRepo, UserProfile

router = APIRouter()

# v2 (decision 41): the inline consent of the 2-screen onboarding; v1 stays valid.
CONSENT_VERSIONS = frozenset({"consent-v1", "consent-v2"})
ContentId = Annotated[str, Field(max_length=120, pattern=r"^[A-Za-z0-9_-]+$")]


def _repo() -> ReaderRepo:
    return ReaderRepo(get_doc_store())


async def signed_in_user(caller: Annotated[Caller, Depends(current_caller)]) -> UserProfile:
    if caller.is_anonymous:
        raise HTTPException(status_code=403, detail="onboarding is for signed-in consumers")
    return await _repo().get_user(caller.uid)


async def consented_user(
    user: Annotated[UserProfile, Depends(signed_in_user)],
) -> UserProfile:
    if user.consent is None:
        raise HTTPException(status_code=409, detail="consent_required")
    return user


class ConsentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str = Field(max_length=32)


@router.post("/me/consent")
async def give_consent(
    body: ConsentIn,
    caller: Annotated[Caller, Depends(current_caller)],
    _: Annotated[UserProfile, Depends(signed_in_user)],
) -> dict[str, Any]:
    if body.version not in CONSENT_VERSIONS:
        raise HTTPException(status_code=422, detail="unknown consent version")
    await _repo().record_consent(caller.uid, body.version, datetime.now(UTC))
    return {"consented": True, "version": body.version}


class OnboardingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: onboarding.Field
    interests: list[Domain] = Field(default_factory=list, max_length=len(DOMAINS))
    comfort: dict[Domain, Level] = Field(default_factory=dict)
    thinks_in: list[ThinksIn] = Field(default_factory=list, max_length=onboarding.MAX_THINKS_IN)
    liked_content_ids: list[ContentId] = Field(
        default_factory=list, max_length=onboarding.MAX_LIKED
    )
    country: Country | None = None  # decision 50: "Where do you read from?"
    # Decision 68 F1: optional (the API deploys first); empty keeps the stored answer.
    formats: list[Format] = Field(default_factory=list, max_length=3)


@router.post("/onboarding")
async def post_onboarding(
    body: OnboardingIn,
    caller: Annotated[Caller, Depends(current_caller)],
    user: Annotated[UserProfile, Depends(consented_user)],
) -> dict[str, Any]:
    graph = get_graph()
    store = get_content_store()
    docs = [d for cid in dict.fromkeys(body.liked_content_ids) if (d := await store.get(cid))]
    now = datetime.now(UTC)
    redo = user.onboarding_done and user.onboarding_redo is not None
    liked: dict[str, tuple[ConceptRef, Any]] = {}
    for cid in onboarding.liked_concepts(docs):
        concept = graph.get(cid)
        if concept is None:
            continue

        def apply(edge, theta, c=concept):  # type: ignore[no-untyped-def]
            return onboarding.apply_liked(c, edge, theta, now)

        liked[cid] = (ConceptRef(concept.domain, concept.base_difficulty), apply)
    # Decision 68 K2: a few terms common where the reader reads from (idempotent: once ever).
    for concept in onboarding.home_terms(graph, body.country or user.country):
        if concept.id in liked:
            continue

        def home(edge, theta, c=concept):  # type: ignore[no-untyped-def]
            return onboarding.apply_home(c, edge, theta, now)

        liked[concept.id] = (ConceptRef(concept.domain, concept.base_difficulty), home)
    answers = {
        "interests": list(dict.fromkeys(body.interests)),
        "comfort": dict(body.comfort),
        "liked_content_ids": [d.content_id for d in docs],
    }
    thinks_in = list(dict.fromkeys(body.thinks_in))
    # Decision 68 K1: the field's domains start at "comfortable" (first-time onboarding only).
    previous = user.field if not user.onboarding_done else None
    theta = (
        onboarding.starting_theta(body.comfort)  # a finished reader's earned θ is never reset
        if user.onboarding_done
        else onboarding.first_theta(body.field, previous, body.comfort)
    )
    if redo:
        # Redo setup (decision 48) deletes nothing: earlier comfort answers and liked articles
        # are kept, frames are kept with the field's frame added, θ isn't reset.
        before = user.onboarding
        answers["comfort"] = dict(before.get("comfort", {})) | answers["comfort"]
        answers["liked_content_ids"] = list(dict.fromkeys(
            [*before.get("liked_content_ids", []), *answers["liked_content_ids"]]))  # fmt: skip
        thinks_in = list(dict.fromkeys([*user.thinks_in, *thinks_in]))[: onboarding.MAX_THINKS_IN]
        theta = {}
    await _repo().save_onboarding(
        caller.uid,
        field=body.field,
        answers=answers,
        thinks_in=thinks_in,
        theta=theta,
        # Edit → Continue (decision 41): screen 2's picks stay applied on top of the new topics.
        interest=onboarding.interests_with_picks(body.interests, user.onboarding_picks),
        liked=liked,
        now=now,
        redo=redo,
        country=body.country,
        formats=list(dict.fromkeys(body.formats)),
    )
    return {"saved": True, "liked_concepts": len(liked), "next": "discover"}


async def _next(caller: Caller, user: UserProfile):  # type: ignore[no-untyped-def]
    """The next term: with a stored Quick check set (decision 68 K4b) its first unanswered one,
    else the adaptive pick (an old client asking one at a time)."""
    asked = list(user.calibration.get("asked", []))
    stored = user.calibration.get("set") or []
    if stored:
        nxt = next((cid for cid in stored if cid not in asked), None)
        return (get_graph().get(nxt) if nxt else None), asked
    domains = await _repo().get_domains(caller.uid)
    theta = {d: s.theta for d, s in domains.items()}
    interests = list(user.onboarding.get("interests", []))
    return onboarding.next_item(get_graph(), interests, theta, asked), asked


@router.get("/calibration/set")
async def calibration_set(
    caller: Annotated[Caller, Depends(current_caller)],
    user: Annotated[UserProfile, Depends(consented_user)],
) -> dict[str, Any]:
    """Decision 68 K4b: the whole Quick check at once, chosen from the current θ and stored, so
    reloads and Edit → Continue show the same terms."""
    total = onboarding.CALIBRATION_ITEMS
    if user.onboarding_done:
        return {"done": True, "total": total, "items": []}
    domains = await _repo().get_domains(caller.uid)
    theta = {d: s.theta for d, s in domains.items()}
    interests = list(user.onboarding.get("interests", []))
    graph = get_graph()
    ids = await _repo().calibration_set(
        caller.uid,
        lambda u: onboarding.quick_set(graph, interests, theta, u.calibration.get("asked", [])),
    )
    asked = set(user.calibration.get("asked", []))
    items = [
        {"concept_id": c.id, "label": c.label, "domain": c.domain, "answered": c.id in asked}
        for cid in ids
        if (c := graph.get(cid)) is not None
    ]
    return {"done": all(i["answered"] for i in items), "total": total, "items": items}


@router.get("/calibration/next")
async def calibration_next(
    caller: Annotated[Caller, Depends(current_caller)],
    user: Annotated[UserProfile, Depends(consented_user)],
) -> dict[str, Any]:
    item, asked = await _next(caller, user)
    total = onboarding.CALIBRATION_ITEMS
    if item is None or user.onboarding_done:
        return {"done": True, "asked": len(asked), "total": total}
    return {
        "done": False,
        "item": {"concept_id": item.id, "label": item.label, "domain": item.domain},
        "asked": len(asked),
        "total": total,
    }


class AnswerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    concept_id: str = Field(max_length=120)
    answer: Answer


@router.post("/calibration/answer", response_model=None)
async def calibration_answer(
    body: AnswerIn,
    caller: Annotated[Caller, Depends(current_caller)],
    user: Annotated[UserProfile, Depends(consented_user)],
) -> dict[str, Any] | JSONResponse:
    """Only a term the reader was shown: an unanswered one of the stored Quick check set
    (decision 68 K4b, any order), or with no set the item /calibration/next would return now. A
    client can't spray answers."""
    stored = user.calibration.get("set") or []
    asked = user.calibration.get("asked", [])
    if stored:
        ok = body.concept_id in stored and body.concept_id not in asked
        item = get_graph().get(body.concept_id) if ok else None
    else:
        item, _ = await _next(caller, user)
    if item is None or item.id != body.concept_id or user.onboarding_done:
        return JSONResponse({"error": "not_the_current_item"}, status_code=409)
    now = datetime.now(UTC)

    def apply(edge, theta):  # type: ignore[no-untyped-def]
        out = onboarding.apply_answer(item, edge, theta, body.answer, now)
        return out.edge, out.theta

    result = await _repo().calibration_answer(
        caller.uid,
        item.id,
        ConceptRef(item.domain, item.base_difficulty),
        apply,
        onboarding.CALIBRATION_ITEMS,
        now,
    )
    if result is None:
        return JSONResponse({"error": "not_the_current_item"}, status_code=409)
    done, answers = result
    return {"done": done, "asked": answers, "total": onboarding.CALIBRATION_ITEMS}


@router.post("/calibration/skip")
async def calibration_skip(
    caller: Annotated[Caller, Depends(current_caller)],
    _: Annotated[UserProfile, Depends(consented_user)],
) -> dict[str, Literal[True]]:
    await _repo().finish_onboarding(caller.uid)
    return {"done": True}


@router.post("/onboarding/redo")
async def start_redo(
    caller: Annotated[Caller, Depends(current_caller)],
    user: Annotated[UserProfile, Depends(consented_user)],
) -> dict[str, Any]:
    """Redo setup (decision 48): a finished reader reruns the 2 screens; nothing is deleted and
    onboarding stays done, so leaving halfway is safe."""
    if not user.onboarding_done:
        raise HTTPException(status_code=409, detail="onboarding_not_done")
    await _repo().start_redo(caller.uid)
    return {"redo": "about"}


@router.post("/onboarding/redo/cancel")
async def cancel_redo(
    caller: Annotated[Caller, Depends(current_caller)],
    _: Annotated[UserProfile, Depends(consented_user)],
) -> dict[str, Any]:
    await _repo().cancel_redo(caller.uid)
    return {"redo": None}
