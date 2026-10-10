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
from app.store.content_repo import get_content_store
from app.store.docstore import get_doc_store
from app.store.reader_repo import ReaderRepo, UserProfile

router = APIRouter()

CONSENT_VERSIONS = frozenset({"consent-v1"})


def _repo() -> ReaderRepo:
    return ReaderRepo(get_doc_store())


async def signed_in_user(caller: Annotated[Caller, Depends(current_caller)]) -> UserProfile:
    if caller.is_anonymous:
        raise HTTPException(status_code=403, detail="onboarding is for signed-in readers")
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
    liked_content_ids: list[str] = Field(default_factory=list, max_length=onboarding.MAX_LIKED)


@router.post("/onboarding")
async def post_onboarding(
    body: OnboardingIn,
    caller: Annotated[Caller, Depends(current_caller)],
    _: Annotated[UserProfile, Depends(consented_user)],
) -> dict[str, Any]:
    graph = get_graph()
    store = get_content_store()
    docs = [d for cid in dict.fromkeys(body.liked_content_ids) if (d := await store.get(cid))]
    now = datetime.now(UTC)
    liked: dict[str, tuple[ConceptRef, Any]] = {}
    for cid in onboarding.liked_concepts(docs):
        concept = graph.get(cid)
        if concept is None:
            continue

        def apply(edge, theta, c=concept):  # type: ignore[no-untyped-def]
            return onboarding.apply_liked(c, edge, theta, now)

        liked[cid] = (ConceptRef(concept.domain, concept.base_difficulty), apply)
    await _repo().save_onboarding(
        caller.uid,
        field=body.field,
        answers={
            "interests": list(dict.fromkeys(body.interests)),
            "comfort": dict(body.comfort),
            "liked_content_ids": [d.content_id for d in docs],
        },
        thinks_in=list(dict.fromkeys(body.thinks_in)),
        theta=onboarding.starting_theta(body.comfort),
        interest=onboarding.interests(body.interests),
        liked=liked,
        now=now,
    )
    return {"saved": True, "liked_concepts": len(liked), "next": "calibration"}


async def _next(caller: Caller, user: UserProfile):  # type: ignore[no-untyped-def]
    domains = await _repo().get_domains(caller.uid)
    theta = {d: s.theta for d, s in domains.items()}
    asked = list(user.calibration.get("asked", []))
    interests = list(user.onboarding.get("interests", []))
    return onboarding.next_item(get_graph(), interests, theta, asked), asked


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
    """Only the item /calibration/next would return now: a client can't spray answers."""
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
