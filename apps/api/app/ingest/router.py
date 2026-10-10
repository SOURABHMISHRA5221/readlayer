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
from app.ingest import quota
from app.ingest.models import ContentDoc, PendingDoc
from app.ingest.safe_fetch import FetchError, validate_url
from app.ingest.urls import url_hash
from app.store.content_repo import get_content_store
from app.store.docstore import get_doc_store
from app.store.pending_repo import AnalysisBusy, AnalysisFailed, NotPending, get_pending_repo
from app.store.reader_repo import ReaderRepo

router = APIRouter()

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


class ParagraphOut(BaseModel):
    id: str
    text: str


class ContentResponse(BaseModel):
    content_id: str
    title: str
    paragraphs: list[ParagraphOut]


def _error(status: int, code: str, message: str, retry_after: int | None = None) -> JSONResponse:
    headers = {"Retry-After": str(retry_after)} if retry_after is not None else None
    return JSONResponse({"error": code, "message": message}, status_code=status, headers=headers)


async def ingest_url(
    url: str, source: Literal["fetch", "user_ingested"] = "fetch", grow_slots: int = 0
) -> ContentDoc:
    """The ingestion pipeline (spaCy, trafilatura, wordfreq, LiteLLM) loads on the first new
    article, so read-only requests and cold starts never import it."""
    from app.ingest import service

    return await service.ingest_url(url, source=source, grow_slots=grow_slots)


async def ingest_submitted(
    url: str, title: str, paragraphs: list[str], grow_slots: int = 0
) -> ContentDoc:
    from app.ingest import service

    return await service.ingest_submitted(url, title, paragraphs, grow_slots)


async def fetch_and_extract(
    url: str, source: Literal["fetch", "user_ingested"], grow_slots: int = 0
) -> PendingDoc:
    from app.ingest import service

    return await service.fetch_and_extract(url, source, grow_slots)


async def analyse_pending(content_id: str) -> ContentDoc:
    from app.ingest import service

    return await service.analyse_pending(content_id)


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


@router.post("/content", response_model=ContentResponse)
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
    known = await is_known(url_hash(body.url))
    if not known and not await quota.reserve(caller, settings):
        return quota.cap_reached(caller, settings, "Articles already in the library stay free.")
    try:
        slots = 0 if known else await quota.reserve_growth(caller, settings)
        if isinstance(body, SubmittedRequest):
            doc = await ingest_submitted(body.url, body.title, body.paragraphs, slots)
            # Submitted text is a reader-brought page: visible to its submitter (M7.5).
            await ReaderRepo(get_doc_store()).add_ingested(
                caller.uid, doc.content_id, datetime.now(UTC).isoformat()
            )
        else:
            doc = await ingest_url(body.url, grow_slots=slots)
    except Exception as exc:
        if not known:
            await quota.refund(caller)
        if isinstance(exc, INGEST_ERRORS):
            return _ingest_error(exc)
        raise
    catalog.add(doc)  # no-op if listed; a URL that was pending is new to the catalog too
    return _response(doc)


class AnalyseResponse(BaseModel):
    content_id: str
    status: Literal["ready", "analysing"]


@router.post("/content/{content_id}/analyse", response_model=AnalyseResponse)
async def analyse_content(
    content_id: Annotated[str, Path(min_length=1, max_length=64, pattern=r"^[0-9a-f]+$")],
    caller: Annotated[Caller, Depends(current_caller)],
) -> AnalyseResponse | JSONResponse:
    """Phase 2 of "Open here": demand extraction and linking for a fetched article. Already
    analysed → ready, no LLM call. Another request analysing it → 202. The ingest slot was taken
    in phase 1, so this costs the reader nothing against the daily cap."""
    try:
        doc = await analyse_pending(content_id)
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


INGEST_ERRORS = (
    FetchError,
    llm.BudgetExceeded,
    llm.LLMUnavailable,
    llm.LLMRejected,
    AnalysisBusy,
    AnalysisFailed,
    TimeoutError,
)


def _ingest_error(exc: Exception) -> JSONResponse:
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


def _response(doc: ContentDoc) -> ContentResponse:
    return ContentResponse(
        content_id=doc.content_id,
        title=doc.title,
        paragraphs=[ParagraphOut(id=p.id, text=p.text) for p in doc.paragraphs],
    )
