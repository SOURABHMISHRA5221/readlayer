"""Whether a feed or Up next item opens in Gloss ("Open here") or only at the source (Media
plan §F, R7). Decided at serve time, so stored demo snapshots need no rewrite."""

import time

from app.config import Settings
from app.media.urls import YouTube, classify
from app.store.media_repo import get_media_day_repo
from app.store.spend_repo import today_utc

ANON_CACHE_S = 60.0
_anon_full: tuple[float, str, bool] | None = None  # (checked at, UTC day, cap used up)


def openable(url: str, fmt: str, duration_s: int | None, settings: Settings) -> bool:
    """Articles always; a YouTube video of known length within the cap; nothing else yet
    (Spotify, show pages and other audio stay "Open original")."""
    if fmt == "article":
        return True
    if not settings.media_enabled or duration_s is None:
        return False
    media = classify(url)
    return isinstance(media, YouTube) and 0 < duration_s <= settings.media_max_video_s


async def anonymous_media_full(settings: Settings) -> bool:
    """All demo readers together have used today's recordings: one read per instance a minute,
    so demo readers stop being offered "Open here" instead of meeting a 429."""
    global _anon_full
    now, day = time.monotonic(), today_utc()
    if _anon_full is None or _anon_full[1] != day or now - _anon_full[0] > ANON_CACHE_S:
        used = await get_media_day_repo().anonymous_opened(day)
        _anon_full = (now, day, used >= settings.anon_global_media_daily_cap)
    return _anon_full[2]


def reset() -> None:
    global _anon_full
    _anon_full = None


async def open_here(
    url: str, fmt: str, duration_s: int | None, settings: Settings, anonymous: bool
) -> bool:
    if not openable(url, fmt, duration_s, settings):
        return False
    return fmt == "article" or not anonymous or not await anonymous_media_full(settings)
