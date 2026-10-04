"""Daily cap on new URLs per reader (CLAUDE.md cost guardrails, DESIGN §11.5).

Only URLs we haven't ingested before count. The slot is reserved in Firestore before the
ingest starts (so parallel requests can't overshoot) and refunded if the ingest fails.
Anonymous readers have a smaller per-uid cap plus one shared cap across all anonymous readers
(`ops/ingest/days/{day}`), so minting new anonymous accounts doesn't multiply the allowance.
"""

from fastapi.responses import JSONResponse

from app.auth import Caller
from app.config import Settings
from app.store.docstore import get_doc_store
from app.store.reader_repo import ReaderRepo
from app.store.spend_repo import today_utc


def _global_path(caller: Caller, day: str) -> str | None:
    return f"ops/ingest/days/{day}" if caller.is_anonymous else None


def per_user_cap(caller: Caller, settings: Settings) -> int:
    return settings.anon_ingest_daily_cap if caller.is_anonymous else settings.ingest_daily_cap


async def reserve(caller: Caller, settings: Settings) -> bool:
    day = today_utc()
    return await ReaderRepo(get_doc_store()).reserve_ingest(
        caller.uid,
        day,
        per_user_cap(caller, settings),
        _global_path(caller, day),
        settings.anon_global_ingest_daily_cap,
    )


async def refund(caller: Caller) -> None:
    day = today_utc()
    await ReaderRepo(get_doc_store()).refund_ingest(caller.uid, day, _global_path(caller, day))


def cap_reached(caller: Caller, settings: Settings, alternative: str) -> JSONResponse:
    if caller.is_anonymous:
        message = (
            "The demo can analyse only a few new articles a day. "
            f"{alternative} Sign in with Google for more."
        )
    else:
        message = (
            f"You can add {settings.ingest_daily_cap} new articles a day. "
            f"{alternative} Or try again tomorrow."
        )
    return JSONResponse({"error": "ingest_cap_reached", "message": message}, status_code=429)
