"""Caller identity for every /v1 route: Firebase ID token in `Authorization: Bearer`.

Accepted sign-in providers: Google and Anonymous (the demo). Tokens are verified with the
Firebase Admin SDK against Google's public certificates; the token and any email in it are
never logged or stored. Logs get a salted `uid_hash` through `uid_hash_var`.

Local dev only: with DEV_AUTH_BYPASS a request *without* an Authorization header acts as
DEV_UID (an anonymous demo reader). Settings refuse the flag on Cloud Run or with ENV=prod,
and `Settings.bypass_allowed` re-checks that on every request.
"""

import contextlib
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any, Protocol

import firebase_admin
from fastapi import Depends, HTTPException, Request
from firebase_admin import auth as fb_auth
from starlette.concurrency import run_in_threadpool

from app.config import Settings, get_settings
from app.log import hash_uid, uid_hash_var
from app.store.docstore import get_doc_store
from app.store.reader_repo import ReaderRepo

log = logging.getLogger("app.auth")

DEV_UID = "dev-local"
PROVIDERS = {"google.com": False, "anonymous": True}  # provider → is_anonymous
KNOWN_USERS_CACHE = 10_000
# A deleted user's ID token stays verifiable until it expires (≤ 1 h). Refuse it here so a
# straggling request can't recreate users/{uid}. Per instance; see STATUS tech debt.
DELETED_TTL_S = 3600.0


@dataclass(frozen=True)
class Caller:
    uid: str
    is_anonymous: bool


class InvalidToken(Exception):
    pass


class AuthAdmin(Protocol):
    async def verify(self, token: str) -> dict[str, Any]: ...

    async def delete_user(self, uid: str) -> None: ...


class FirebaseAuthAdmin:
    def __init__(self, project: str) -> None:
        name = f"readlayer-{project or 'default'}"
        try:
            self._app = firebase_admin.get_app(name)
        except ValueError:
            options = {"projectId": project} if project else None
            self._app = firebase_admin.initialize_app(options=options, name=name)

    async def verify(self, token: str) -> dict[str, Any]:
        try:
            return await run_in_threadpool(
                fb_auth.verify_id_token, token, app=self._app, clock_skew_seconds=10
            )
        except (fb_auth.InvalidIdTokenError, fb_auth.UserDisabledError, ValueError) as exc:
            # ExpiredIdTokenError and RevokedIdTokenError subclass InvalidIdTokenError.
            raise InvalidToken(type(exc).__name__) from exc

    async def delete_user(self, uid: str) -> None:
        with contextlib.suppress(fb_auth.UserNotFoundError):  # already gone: idempotent
            await run_in_threadpool(fb_auth.delete_user, uid, app=self._app)


_admin: AuthAdmin | None = None
_known: OrderedDict[str, None] = OrderedDict()  # uids whose users/{uid} doc exists
_deleted: dict[str, float] = {}  # uid → monotonic time of deletion


def get_auth_admin() -> AuthAdmin:
    global _admin
    if _admin is None:
        _admin = FirebaseAuthAdmin(get_settings().auth_project)
    return _admin


def set_auth_admin(admin: AuthAdmin | None) -> None:
    global _admin
    _admin = admin
    _known.clear()
    _deleted.clear()


def forget_user(uid: str, *, deleted: bool = False) -> None:
    _known.pop(uid, None)
    if deleted:
        now = time.monotonic()
        for k in [k for k, t in _deleted.items() if now - t > DELETED_TTL_S]:
            del _deleted[k]
        _deleted[uid] = now


def _recently_deleted(uid: str) -> bool:
    at = _deleted.get(uid)
    return at is not None and time.monotonic() - at <= DELETED_TTL_S


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization")
    if header is None:
        return None
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="sign-in required")
    return token.strip()


async def _ensure_user(caller: Caller) -> None:
    if caller.uid in _known:
        _known.move_to_end(caller.uid)
        return
    await ReaderRepo(get_doc_store()).ensure_user(
        caller.uid, caller.is_anonymous, datetime.now(UTC)
    )
    _known[caller.uid] = None
    while len(_known) > KNOWN_USERS_CACHE:
        _known.popitem(last=False)


async def current_caller(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
) -> Caller:
    token = _bearer(request)
    if token is None:
        if not settings.bypass_allowed:
            raise HTTPException(status_code=401, detail="sign-in required")
        caller = Caller(DEV_UID, is_anonymous=True)
    else:
        try:
            claims = await get_auth_admin().verify(token)
        except InvalidToken as exc:
            log.info("token rejected", extra={"reason": str(exc)})
            raise HTTPException(status_code=401, detail="sign-in required") from None
        provider = (claims.get("firebase") or {}).get("sign_in_provider")
        if provider not in PROVIDERS:
            raise HTTPException(status_code=403, detail="sign-in method not allowed")
        caller = Caller(str(claims["uid"]), PROVIDERS[provider])
        if _recently_deleted(caller.uid):
            raise HTTPException(status_code=401, detail="account deleted")
    uid_hash = hash_uid(caller.uid, settings.uid_hash_salt)
    uid_hash_var.set(uid_hash)
    request.state.uid_hash = uid_hash  # for the request log line written by the middleware
    await _ensure_user(caller)
    return caller


async def current_uid(caller: Annotated[Caller, Depends(current_caller)]) -> str:
    return caller.uid
