"""POST /v1/internal/feeds/collect: the twice-daily outlet collection (decision 50).

Mounted outside the Firebase-authenticated /v1 router: only Cloud Scheduler calls it, with a
Google-signed OIDC ID token for FEED_JOB_SA_EMAIL. Required: a valid signature, `iss`
accounts.google.com, `aud` == FEED_JOB_AUDIENCE (configured, never derived from the request:
Cloud Run answers on two URLs), `email_verified`, `email` == FEED_JOB_SA_EMAIL. Either setting
missing → 403 (fail closed). A Firebase ID token fails these checks (wrong issuer/audience).
"""

import asyncio
import logging
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request

from app.config import Settings, get_settings
from app.ingest.safe_fetch import SafeFetcher
from app.recs.feed import now_utc
from app.recs.outlet_job import collect
from app.store.docstore import get_doc_store
from app.store.outlet_repo import OutletStore

log = logging.getLogger("app.recs.internal")
router = APIRouter(prefix="/internal")

GOOGLE_ISSUERS = frozenset({"accounts.google.com", "https://accounts.google.com"})
Verifier = Callable[[str, str], dict[str, Any]]  # (token, audience) → claims, raises if invalid

_session: Any = None


def _google_verify(token: str, audience: str) -> dict[str, Any]:
    """Signature, expiry and audience checked by google-auth against Google's certs (the
    session caches them)."""
    global _session
    import cachecontrol
    import google.auth.transport.requests
    import requests
    from google.oauth2 import id_token

    if _session is None:
        _session = cachecontrol.CacheControl(requests.session())
    request = google.auth.transport.requests.Request(session=_session)
    return dict(id_token.verify_oauth2_token(token, request, audience=audience))


_verify: Verifier = _google_verify


def set_verifier(verifier: Verifier | None) -> None:
    global _verify
    _verify = verifier or _google_verify


def _forbidden() -> HTTPException:
    return HTTPException(status_code=403, detail="forbidden")


async def scheduler_caller(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
) -> None:
    sa, audience = settings.feed_job_sa_email, settings.feed_job_audience
    header = request.headers.get("authorization", "")
    if not sa or not audience or not header.lower().startswith("bearer "):
        raise _forbidden()
    try:
        claims = await asyncio.to_thread(_verify, header[7:].strip(), audience)
    except Exception as exc:  # any verification failure is a plain 403; the token isn't logged
        log.warning("collect token refused", extra={"error_class": type(exc).__name__})
        raise _forbidden() from None
    if (
        claims.get("iss") not in GOOGLE_ISSUERS
        or claims.get("aud") != audience
        or claims.get("email_verified") is not True
        or claims.get("email") != sa
    ):
        log.warning("collect token refused", extra={"error_class": "claims"})
        raise _forbidden()


@router.post("/feeds/collect", dependencies=[Depends(scheduler_caller)])
async def collect_feeds() -> dict[str, Any]:
    report = await collect(SafeFetcher(), OutletStore(get_doc_store()), now_utc())
    return {
        "feeds_ok": report.feeds_ok,
        "feeds_failed": report.feeds_failed,
        "fresh": report.fresh,
        "stored": report.stored,
    }
