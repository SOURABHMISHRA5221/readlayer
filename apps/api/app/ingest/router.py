"""POST /v1/content (DESIGN §8): both input shapes, with explicit error statuses."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app import llm
from app.ingest.models import ContentDoc
from app.ingest.safe_fetch import FetchError
from app.ingest.service import ingest_submitted, ingest_url

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


def _seconds_to_utc_midnight(now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(1, int((midnight - now).total_seconds()))


# TODO(M3): require a Firebase ID token and enforce the per-user daily cap on new URLs.
@router.post("/content", response_model=ContentResponse)
async def post_content(body: SubmittedRequest | UrlRequest) -> ContentResponse | JSONResponse:
    if isinstance(body, SubmittedRequest) and any(
        len(p) > MAX_SUBMITTED_PARAGRAPH_CHARS for p in body.paragraphs
    ):
        return _error(422, "paragraph_too_long", "a paragraph exceeds the size limit")
    try:
        if isinstance(body, SubmittedRequest):
            doc = await ingest_submitted(body.url, body.title, body.paragraphs)
        else:
            doc = await ingest_url(body.url)
    except FetchError as exc:
        return _error(FETCH_ERROR_STATUS[exc.code], exc.code, exc.message)
    except llm.BudgetExceeded:
        return _error(
            503,
            "llm_budget_exceeded",
            "Today's analysis budget is used up and this article hasn't been analysed before. "
            "Try again after midnight UTC.",
            retry_after=_seconds_to_utc_midnight(),
        )
    except llm.LLMUnavailable:
        return _error(
            503,
            "llm_unavailable",
            "The analysis model is temporarily unavailable. Try again in a minute.",
            retry_after=60,
        )
    except llm.LLMRejected:
        return _error(502, "llm_rejected", "The analysis request failed. This has been logged.")
    return _response(doc)


def _response(doc: ContentDoc) -> ContentResponse:
    return ContentResponse(
        content_id=doc.content_id,
        title=doc.title,
        paragraphs=[ParagraphOut(id=p.id, text=p.text) for p in doc.paragraphs],
    )
