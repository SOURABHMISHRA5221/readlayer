"""Daily cap on new URLs per reader (CLAUDE.md cost guardrails, DESIGN §11.5).

Only URLs we haven't ingested before count. The slot is reserved in Firestore before the
ingest starts (so parallel requests can't overshoot) and refunded if the ingest fails.
Anonymous readers have a smaller per-uid cap plus one shared cap across all anonymous readers
(`ops/ingest/days/{day}`), so minting new anonymous accounts doesn't multiply the allowance.
"""

from collections.abc import Awaitable, Callable

from fastapi.responses import JSONResponse

from app.auth import Caller
from app.config import Settings
from app.store.docstore import get_doc_store
from app.store.reader_repo import ReaderRepo
from app.store.spend_repo import today_utc

Reserver = Callable[[int], Awaitable[int]]  # want → granted (M9: slots taken when used)


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


def growth_reserver(caller: Caller, settings: Settings) -> Reserver | None:
    """Concept-growth slots for this caller (M9 part 1): phase 2 and /grow call it with the number
    of labels growth will try, once they know it, and get what the caps allow (at most one
    article's worth). None when growth is off. The pending and content docs never learn who
    reserved: the uid stays in this closure."""
    if not settings.growth_enabled:
        return None
    from app.store.growth_repo import GrowthRepo

    async def reserve(want: int) -> int:
        want = min(want, settings.growth_per_article)
        if want <= 0:
            return 0
        return await GrowthRepo(get_doc_store()).reserve_slots(
            caller.uid,
            today_utc(),
            want,
            settings.growth_per_uid_day,
            settings.growth_per_day,
            settings.anon_growth_daily_cap if caller.is_anonymous else None,
        )

    return reserve


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
