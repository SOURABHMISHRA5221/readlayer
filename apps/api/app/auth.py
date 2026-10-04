"""Caller identity for /v1 routes.

Firebase ID-token verification lands in M3. Until then the only way in is the local dev bypass,
which config refuses to enable on Cloud Run (`Settings._no_auth_bypass_when_deployed`).
"""

from typing import Annotated

from fastapi import Depends, HTTPException

from app.config import Settings, get_settings
from app.log import hash_uid, uid_hash_var

DEV_UID = "dev-local"


async def current_uid(settings: Annotated[Settings, Depends(get_settings)]) -> str:
    if not settings.dev_auth_bypass:
        raise HTTPException(status_code=401, detail="sign-in required")
    uid_hash_var.set(hash_uid(DEV_UID, settings.uid_hash_salt))
    return DEV_UID
