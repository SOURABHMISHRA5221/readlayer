"""POST /v1/content (DESIGN §8): both input shapes, with explicit error statuses."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app import llm
from app.auth import Caller, current_caller
from app.config import Settings, get_settings
from app.content import catalog
from app.content.access import require_readable
from app.ingest import quota, submitted
from app.ingest.models import ContentDoc, PendingDoc
from app.ingest.safe_fetch import FetchError, validate_url
from app.ingest.urls import ext_id, url_hash
from app.media.urls import classify
from app.privacy.redact import count_redactions, redact, redact_url
from app.store.content_repo import get_content_store
from app.store.docstore import get_doc_store
from app.store.pending_repo import (
    AnalysisBusy,
    AnalysisFailed,
    ContentTranscribing,
    NotPending,
    get_pending_repo,
)
from app.store.reader_repo import ReaderRepo

router = APIRouter()

PERSONAL_DATA = "This page looks like it holds personal information, so Gloss won't read it."
MAX_URL_CHARS = 2048
MAX_SUBMITTED_PARAGRAPHS = 200
MAX_SUBMITTED_PARAGRAPH_CHARS = 5000

FETCH_ERROR_STATUS = {
    "unsafe_url": 400,
    "robots_disallowed": 403,
    "not_html": 415,
    "too_large": 413,
    "too_many_redirects": 502,
    "timeout": 504,
    "upstream_error": 502,
    "no_article_text": 422,
}


class UrlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(max_length=MAX_URL_CHARS)


class SubmittedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(max_length=MAX_URL_CHARS)
    title: str = Field(max_length=500)
    paragraphs: list[str] = Field(
        min_length=1,
        max_length=MAX_SUBMITTED_PARAGRAPHS,
        json_schema_extra={"items": {"maxLength": MAX_SUBMITTED_PARAGRAPH_CHARS}},
    )
    # Return as soon as the text is stored ("analysing"); the client then calls
    # POST /v1/content/{id}/analyse, as "Open here" does (M8).
    defer: bool = False


class ParagraphOut(BaseModel):
    id: str
    text: str


class ContentResponse(BaseModel):
    content_id: str
    title: str
    paragraphs: list[ParagraphOut]
    status: Literal["ready", "analysing"] = "ready"
    # Submitted text only: placeholders the server's redactor added, i.e. personal data the
    # client's redaction missed (0 when the extension did its job). Absent for URL bodies.
    pii_found_before_backstop: int | None = None


def _error(status: int, code: str, message: str, retry_after: int | None = None) -> JSONResponse:
    headers = {"Retry-After": str(retry_after)} if retry_after is not None else None
    return JSONResponse({"error": code, "message": message}, status_code=status, headers=headers)


async def ingest_url(
    url: str,
    source: Literal["fetch", "user_ingested"] = "fetch",
    reserve: quota.Reserver | None = None,
) -> ContentDoc:
    """The ingestion pipeline (spaCy, trafilatura, wordfreq, LiteLLM) loads on the first new
    article, so read-only requests and cold starts never import it."""
    from app.ingest import service

    return await service.ingest_url(url, source=source, reserve=reserve)


def clean_submitted(paragraphs: list[str]) -> list[str]:
    from app.ingest import service

    return service.clean_submitted(paragraphs)


async def pii_refuses(paragraphs: list[str]) -> bool:
    from app.ingest import service

    return (await service.pii_check(paragraphs)).refuse


async def store_submitted(content_id: str, url: str, title: str, texts: list[str]) -> PendingDoc:
    from app.ingest import service

    return await service.store_submitted(content_id, url, title, texts)


async def fetch_and_extract(url: str, source: Literal["fetch", "user_ingested"]) -> PendingDoc:
    from app.ingest import service

    return await service.fetch_and_extract(url, source)


async def analyse_pending(content_id: str, reserve: quota.Reserver | None = None) -> ContentDoc:
    from app.ingest import service

    return await service.analyse_pending(content_id, reserve)


async def is_known(content_id: str) -> bool:
    """Already ingested, or fetched and waiting for analysis: either way no new fetch and no
    new slot against the daily cap."""
    if await get_content_store().get(content_id) is not None:
        return True
    return await get_pending_repo().get(content_id) is not None


def _seconds_to_utc_midnight(now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(1, int((midnight - now).total_seconds()))


@router.post("/content", response_model=ContentResponse, response_model_exclude_none=True)
async def post_content(
    body: SubmittedRequest | UrlRequest,
    caller: Annotated[Caller, Depends(current_caller)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ContentResponse | JSONResponse:
    """Authenticated (router dependency) and within the per-user daily cap on new URLs."""
    if isinstance(body, SubmittedRequest) and any(
        len(p) > MAX_SUBMITTED_PARAGRAPH_CHARS for p in body.paragraphs
    ):
        return _error(422, "paragraph_too_long", "a paragraph exceeds the size limit")
    try:
        validate_url(body.url)
    except FetchError as exc:
        return _error(FETCH_ERROR_STATUS[exc.code], exc.code, exc.message)
    if classify(body.url) is not None:  # both shapes, before any lookup or slot (plan R4)
        return _error(422, "use_open_here", "Open it in Gloss with Read any link.")
    if isinstance(body, SubmittedRequest):
        return await _post_submitted(body, caller, settings)
    known = await is_known(url_hash(body.url))
    if not known and not await quota.reserve(caller, settings):
        return quota.cap_reached(caller, settings, "Articles already in the library stay free.")
    try:  # growth slots are taken in phase 2, for what it tries (M9), even for a pending URL
        doc = await ingest_url(body.url, reserve=quota.growth_reserver(caller, settings))
    except Exception as exc:
        if not known:
            await quota.refund(caller)
        if isinstance(exc, INGEST_ERRORS):
            return _ingest_error(exc)
        raise
    catalog.add(doc)  # no-op if listed; a URL that was pending is new to the catalog too
    return _response(doc)


async def _post_submitted(
    body: SubmittedRequest, caller: Caller, settings: Settings
) -> ContentResponse | JSONResponse:
    """Extension text (M8): an existing doc if there is one (free), else a new `ext:` doc."""
    if not caller.is_anonymous and not await submitted.onboarded(caller.uid):
        return _error(409, "onboarding_required", "Finish setting up Gloss in the web app first.")
    found = 0
    # The server's redaction covers the URL and title too, not only the paragraphs.
    url, title = redact_url(body.url), redact(body.title)
    try:
        doc: ContentDoc | PendingDoc | None = await submitted.reusable(caller.uid, url)
        if doc is None:
            cleaned = clean_submitted(body.paragraphs)
            texts = [redact(t) for t in cleaned]  # the server's redaction on top of the client's
            found = sum(count_redactions(t) for t in body.paragraphs)
            content_id = ext_id(url, texts)
            doc = await submitted.get_any(content_id)
            if doc is None:
                if await pii_refuses(cleaned):  # before anything is stored or charged
                    return _error(422, "personal_data", PERSONAL_DATA)
                if not await quota.reserve(caller, settings):
                    return quota.cap_reached(
                        caller, settings, "Articles already in the library stay free."
                    )
                try:
                    doc = await store_submitted(content_id, url, title, texts)
                except Exception:
                    await quota.refund(caller)
                    raise
        # The reader brought it in: their library lists it and they may read it (M7.5, A5).
        await ReaderRepo(get_doc_store()).add_ingested(
            caller.uid, doc.content_id, datetime.now(UTC).isoformat()
        )
        if isinstance(doc, PendingDoc) and not body.defer:
            doc = await analyse_pending(doc.content_id, quota.growth_reserver(caller, settings))
    except Exception as exc:
        if isinstance(exc, INGEST_ERRORS):
            return _ingest_error(exc)
        raise
    if isinstance(doc, PendingDoc):
        return _pending_response(doc, found)
    catalog.add(doc)
    return _response(doc).model_copy(update={"pii_found_before_backstop": found})


class AnalyseResponse(BaseModel):
    content_id: str
    status: Literal["ready", "analysing"]


@router.post("/content/{content_id}/analyse", response_model=AnalyseResponse)
async def analyse_content(
    content_id: Annotated[str, Path(min_length=1, max_length=64, pattern=r"^[0-9a-f]+$")],
    caller: Annotated[Caller, Depends(current_caller)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AnalyseResponse | JSONResponse:
    """Phase 2 of "Open here": demand extraction and linking for a fetched article. Already
    analysed → ready, no LLM call. Another request analysing it → 202. The ingest slot was taken
    in phase 1, so this costs the reader nothing against the daily cap. Extension text: its
    submitters only (M8 §A5)."""
    if (pending := await get_pending_repo().get(content_id)) is not None:
        await require_readable(pending, caller.uid)
    try:
        doc = await analyse_pending(content_id, quota.growth_reserver(caller, settings))
    except NotPending:
        return _error(404, "not_found", "content not found")
    except AnalysisBusy:
        return JSONResponse({"content_id": content_id, "status": "analysing"}, status_code=202)
    except Exception as exc:
        if isinstance(exc, INGEST_ERRORS):
            return _ingest_error(exc)
        raise
    catalog.add(doc)
    return AnalyseResponse(content_id=content_id, status="ready")


class GrowResponse(BaseModel):
    content_id: str
    status: Literal["none", "capped", "grown", "growing"]
    linked: int = 0


@router.post("/content/{content_id}/grow", response_model=GrowResponse)
async def grow_content(
    content_id: Annotated[str, Path(min_length=1, max_length=64, pattern=r"^[0-9a-f]+$")],
    caller: Annotated[Caller, Depends(current_caller)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> GrowResponse | JSONResponse:
    """A reader's stored page that missed concept growth (the caps ran out, M9 part 1): grow it
    now with this reader's slots, so its ideas join the map and its notes appear. "none" (no
    model call): nothing to grow; "capped": no slots left today; "grown": `linked` demands now
    link; 202 "growing": another request is on it. Never part of the scoring path. Extension
    pages: their submitters only."""
    doc = await get_content_store().get(content_id)
    if doc is None:
        return _error(404, "not_found", "content not found")
    await require_readable(doc, caller.uid)
    from app.ingest.growing import grow_stored

    done = await grow_stored(doc, quota.growth_reserver(caller, settings))
    if done.status == "budget":
        return _ingest_error(llm.BudgetExceeded("daily LLM budget reached"))
    if done.status == "growing":
        return JSONResponse({"content_id": content_id, "status": "growing"}, status_code=202)
    return GrowResponse(content_id=content_id, status=done.status, linked=done.linked)


class TranscribeResponse(BaseModel):
    content_id: str
    status: Literal["analysing"]


@router.post("/content/{content_id}/transcribe", response_model=TranscribeResponse)
async def transcribe_content(
    content_id: Annotated[str, Path(min_length=1, max_length=64, pattern=r"^[0-9a-f]+$")],
    caller: Annotated[Caller, Depends(current_caller)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TranscribeResponse | JSONResponse:
    """A recording's transcript (DESIGN §21), then the client calls .../analyse as for an
    article. Already transcribed → 200 with no model call; another request transcribing → 202;
    a refusal → 422 with its code. The media slot was taken when it was opened."""
    from app.media.refusals import MediaRefused, MediaUnavailable, message
    from app.media.service import TranscribeBusy, transcribe_pending

    if (pending := await get_pending_repo().get(content_id)) is not None:
        await require_readable(pending, caller.uid)
    try:
        await transcribe_pending(content_id, settings)
    except NotPending:
        return _error(404, "not_found", "content not found")
    except TranscribeBusy:
        return JSONResponse(
            {"content_id": content_id, "status": "transcribing"},
            status_code=202,
            headers={"Retry-After": "5"},
        )
    except MediaRefused as exc:
        return _error(422, exc.code, message(exc.code))
    except MediaUnavailable:  # the episode's host timed out or failed: not remembered (5R5)
        return _error(503, "media_unavailable", message("media_unavailable"), retry_after=60)
    except AnalysisFailed:
        return _error(
            410, "transcribe_failed", "Gloss couldn't transcribe this. Open the original instead."
        )
    except TimeoutError:
        return _error(504, "transcribe_timeout", "Transcribing took too long. Try again.")
    except Exception as exc:
        if isinstance(exc, INGEST_ERRORS):
            return _ingest_error(exc)
        raise
    return TranscribeResponse(content_id=content_id, status="analysing")


INGEST_ERRORS = (
    FetchError,
    llm.BudgetExceeded,
    llm.LLMUnavailable,
    llm.LLMRejected,
    AnalysisBusy,
    AnalysisFailed,
    ContentTranscribing,
    TimeoutError,
)


def _ingest_error(exc: Exception) -> JSONResponse:
    if isinstance(exc, ContentTranscribing):
        return _error(
            409,
            "content_transcribing",
            "This recording is being transcribed. Try again shortly.",
            5,
        )
    if isinstance(exc, AnalysisBusy):
        return _error(
            409, "content_analysing", "This article is being analysed. Try again shortly.", 5
        )
    if isinstance(exc, AnalysisFailed):
        return _error(
            410, "analyse_failed", "This article couldn't be analysed. Open the original instead."
        )
    if isinstance(exc, TimeoutError):
        return _error(504, "analyse_timeout", "Analysing this article took too long. Try again.")
    if isinstance(exc, FetchError):
        return _error(FETCH_ERROR_STATUS[exc.code], exc.code, exc.message)
    if isinstance(exc, llm.BudgetExceeded):
        return _error(
            503,
            "llm_budget_exceeded",
            "Today's analysis budget is used up and this article hasn't been analysed before. "
            "Try again after midnight UTC.",
            retry_after=_seconds_to_utc_midnight(),
        )
    if isinstance(exc, llm.LLMUnavailable):
        return _error(
            503,
            "llm_unavailable",
            "The analysis model is temporarily unavailable. Try again in a minute.",
            retry_after=60,
        )
    return _error(502, "llm_rejected", "The analysis request failed. This has been logged.")


def _pending_response(doc: PendingDoc, found: int) -> ContentResponse:
    return ContentResponse(
        content_id=doc.content_id,
        title=doc.title,
        paragraphs=[ParagraphOut(id=p.id, text=p.text) for p in doc.paragraphs],
        status="analysing",
        pii_found_before_backstop=found,
    )


def _response(doc: ContentDoc) -> ContentResponse:
    return ContentResponse(
        content_id=doc.content_id,
        title=doc.title,
        paragraphs=[ParagraphOut(id=p.id, text=p.text) for p in doc.paragraphs],
    )
