"""Public metadata for a recording, and the checks made before any model call (Media plan §A).

Only public ids leave the server: a YouTube video id with the server's API key, or Apple's two
numeric ids. Nothing about the reader. Errors are logged by status only, never by URL (the
YouTube URL carries the key).
"""

import logging
from dataclasses import dataclass

import httpx

from app.config import Settings
from app.media.refusals import MediaRefused, MediaUnavailable
from app.recs.feed_rank import mostly_latin
from app.recs.web_search import YOUTUBE_VIDEOS_URL, parse_iso_duration

log = logging.getLogger("app.media")

MIN_DURATION_S = 30
MAX_TITLE_CHARS = 300


@dataclass(frozen=True)
class MediaInfo:
    title: str
    site: str  # the channel or show
    duration_s: int
    image: str | None = None
    published: str | None = None
    language: str | None = None  # declared spoken language, when the source gives one


async def youtube_info(
    video_id: str, settings: Settings, transport: httpx.AsyncBaseTransport | None = None
) -> MediaInfo:
    """videos.list (1 quota unit). Raises MediaRefused or MediaUnavailable."""
    key = settings.youtube_api_key.get_secret_value()
    if not key:
        raise MediaRefused("media_off")
    params = {"part": "contentDetails,status,snippet", "id": video_id, "key": key}
    try:
        async with httpx.AsyncClient(
            timeout=settings.search_timeout_s, transport=transport
        ) as client:
            resp = await client.get(YOUTUBE_VIDEOS_URL, params=params)
    except httpx.HTTPError as exc:
        log.warning("youtube lookup failed", extra={"error_class": type(exc).__name__})
        raise MediaUnavailable("youtube") from None
    if resp.status_code != 200:
        log.warning("youtube lookup failed", extra={"status": resp.status_code})
        raise MediaUnavailable("youtube")
    items = resp.json().get("items") or []
    if not items:
        raise MediaRefused("not_public")  # deleted, private or never existed
    return _check_video(items[0], settings)


def _check_video(item: dict, settings: Settings) -> MediaInfo:
    status = item.get("status") or {}
    snippet = item.get("snippet") or {}
    details = item.get("contentDetails") or {}
    if status.get("privacyStatus") != "public" or status.get("uploadStatus") not in (
        None,
        "processed",
    ):
        raise MediaRefused("not_public")
    if status.get("embeddable") is False:
        raise MediaRefused("not_embeddable")
    if (details.get("contentRating") or {}).get("ytRating") == "ytAgeRestricted":
        raise MediaRefused("not_embeddable")  # the embedded player won't play it signed out
    if snippet.get("liveBroadcastContent", "none") != "none":
        raise MediaRefused("live")
    duration = parse_iso_duration(details.get("duration"))
    if duration is None:
        raise MediaRefused("live")  # live streams report P0D
    if duration < MIN_DURATION_S:
        raise MediaRefused("no_speech")
    if duration > settings.media_max_video_s:
        raise MediaRefused("too_long")
    title = str(snippet.get("title") or "").strip()[:MAX_TITLE_CHARS]
    language = snippet.get("defaultAudioLanguage") or None
    if (language and not str(language).lower().startswith("en")) or not mostly_latin(title):
        raise MediaRefused("not_english")
    thumbs = snippet.get("thumbnails") or {}
    thumb = thumbs.get("high") or thumbs.get("medium") or thumbs.get("default") or {}
    return MediaInfo(
        title=title or "YouTube video",
        site=str(snippet.get("channelTitle") or "YouTube")[:120],
        duration_s=duration,
        image=_https(thumb.get("url")),
        published=str(snippet.get("publishedAt") or "")[:32] or None,
        language=str(language) if language else None,
    )


def _https(url: object) -> str | None:
    return url if isinstance(url, str) and url.startswith("https://") and len(url) < 1000 else None
