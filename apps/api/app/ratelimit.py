"""Per-uid request limits per minute (DESIGN §11.5), sliding window, in memory per instance.

With at most 3 Cloud Run instances a reader can get up to 3× a limit in the worst case; the
limits that protect money (new URLs per day, web searches, LLM budget) are in Firestore.
"""

import math
import time
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, HTTPException

from app.auth import Caller, current_caller
from app.config import Settings, get_settings

WINDOW_S = 60.0
_hits: dict[tuple[str, str], deque[float]] = {}
_calls = 0


def reset() -> None:
    _hits.clear()


def check(key: tuple[str, str], limit: int, now: float | None = None) -> float | None:
    """Record a hit; None if allowed, else seconds until the oldest hit leaves the window."""
    global _calls
    now = time.monotonic() if now is None else now
    hits = _hits.setdefault(key, deque())
    while hits and now - hits[0] >= WINDOW_S:
        hits.popleft()
    if len(hits) >= limit:
        return WINDOW_S - (now - hits[0])
    hits.append(now)
    _calls += 1
    if _calls % 1000 == 0:  # drop idle readers now and then
        for k in [k for k, v in _hits.items() if not v or now - v[-1] >= WINDOW_S]:
            del _hits[k]
    return None


def limit(
    bucket: str, per_min: Callable[[Settings], int], anon_per_min: Callable[[Settings], int]
) -> Callable[..., Awaitable[None]]:
    async def dependency(
        caller: Annotated[Caller, Depends(current_caller)],
        settings: Annotated[Settings, Depends(get_settings)],
    ) -> None:
        cap = anon_per_min(settings) if caller.is_anonymous else per_min(settings)
        wait = check((caller.uid, bucket), cap)
        if wait is not None:
            raise HTTPException(
                status_code=429,
                detail="Too many requests. Slow down for a moment.",
                headers={"Retry-After": str(max(1, math.ceil(wait)))},
            )

    return dependency


general = limit("general", lambda s: s.rate_general_per_min, lambda s: s.rate_general_anon_per_min)
annotations = limit(
    "annotations", lambda s: s.rate_annotations_per_min, lambda s: s.rate_annotations_anon_per_min
)
events = limit("events", lambda s: s.rate_events_per_min, lambda s: s.rate_events_per_min)
