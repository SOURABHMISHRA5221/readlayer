"""Whether a feed or Up next item opens in Gloss ("Open here") or only at the source (Media
plan §F, R7). Decided at serve time, so stored demo snapshots need no rewrite."""

import time

from app.config import Settings
from app.ingest.models import MediaKind
from app.media.urls import ApplePodcast, Media, YouTube, classify
from app.store.media_repo import get_media_day_repo
from app.store.spend_repo import today_utc

ANON_CACHE_S = 60.0
_anon_full: tuple[float, str, bool] | None = None  # (checked at, UTC day, cap used up)


def media_kind(media: Media) -> MediaKind:
    return "youtube" if isinstance(media, YouTube) else "audio"


def media_kind_on(kind: MediaKind, settings: Settings) -> bool:
    """The kill switch and the kind's own switch (5.1). Read on every open, transcribe and
    serve, never stored: turning a switch back on works at once."""
    if not settings.media_enabled:
        return False
    return settings.media_video_enabled if kind == "youtube" else settings.media_audio_enabled


def openable(url: str, fmt: str, duration_s: int | None, settings: Settings) -> bool:
    """Articles always; a YouTube video or an Apple episode of known length within the cap.
    Unknown lengths stay "Open original": under the short caps most episodes run past them
    (median 22 min in the cached links), so "Open here" would end in a refusal. Spotify, show
    pages and direct .mp3 links stay "Open original"."""
    if fmt == "article":
        return True
    media = classify(url)
    if media is None or not media_kind_on(media_kind(media), settings):
        return False
    if isinstance(media, YouTube):
        return duration_s is not None and 0 < duration_s <= settings.media_max_video_s
    if isinstance(media, ApplePodcast) and media.episode_id:
        return duration_s is not None and 0 < duration_s <= settings.media_max_audio_s
    return False


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
