"""Public metadata for a recording, and the checks made before any model call (Media plan §A).

Only public ids leave the server: a YouTube video id with the server's API key, or Apple's two
numeric ids. Nothing about the reader. Errors are logged by status only, never by URL (the
YouTube URL carries the key; an episode's audio URL is the publisher's and stays out of logs).
"""

import logging
from dataclasses import dataclass

import httpx

from app.config import Settings
from app.ingest.safe_fetch import FetchError, SafeFetcher, is_transient
from app.media import mp3
from app.media.refusals import MediaRefused, MediaUnavailable
from app.recs.feed_rank import mostly_latin
from app.recs.web_search import YOUTUBE_VIDEOS_URL, parse_iso_duration

log = logging.getLogger("app.media")

MIN_DURATION_S = 30
MAX_TITLE_CHARS = 300
MAX_SITE_CHARS = 120
MAX_AUDIO_URL_CHARS = 2048
APPLE_LOOKUP_URL = "https://itunes.apple.com/lookup"
APPLE_LOOKUP_LIMIT = 200  # Apple's maximum: older episodes aren't found (episode_not_found)
TAG_PROBE_BYTES = 16 * 1024  # read at the end of an ID3 tag bigger than the head (5R1)


@dataclass(frozen=True)
class MediaInfo:
    title: str
    site: str  # the channel or show
    duration_s: int
    image: str | None = None
    published: str | None = None
    language: str | None = None  # declared spoken language, when the source gives one
    audio_url: str | None = None  # a podcast episode's MP3


@dataclass(frozen=True)
class AudioProbe:
    """What the open learns from an episode's first bytes (no model call)."""

    final_url: str
    total_bytes: int
    bitrate_kbps: int


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


async def apple_episode(
    show_id: str,
    episode_id: str | None,
    settings: Settings,
    transport: httpx.AsyncBaseTransport | None = None,
) -> MediaInfo:
    """Apple's public lookup for a show's latest 200 episodes; the one with our id. Raises
    MediaRefused or MediaUnavailable. A show page is refused before any lookup."""
    if episode_id is None:
        raise MediaRefused("not_an_episode")
    params = {"id": show_id, "entity": "podcastEpisode", "limit": str(APPLE_LOOKUP_LIMIT)}
    try:
        async with httpx.AsyncClient(
            timeout=settings.search_timeout_s, transport=transport
        ) as client:
            resp = await client.get(APPLE_LOOKUP_URL, params=params)
        results = resp.json().get("results") if resp.status_code == 200 else None
    except (httpx.HTTPError, ValueError, AttributeError) as exc:
        log.warning("apple lookup failed", extra={"error_class": type(exc).__name__})
        raise MediaUnavailable("apple") from None
    if not isinstance(results, list):
        log.warning("apple lookup failed", extra={"status": resp.status_code})
        raise MediaUnavailable("apple")
    wanted = int(episode_id)
    item = next(
        (r for r in results if isinstance(r, dict) and _int(r.get("trackId")) == wanted), None
    )
    if item is None:
        raise MediaRefused("episode_not_found")
    return _check_episode(item, settings)


def _check_episode(item: dict, settings: Settings) -> MediaInfo:
    audio_url = item.get("episodeUrl")
    if not (
        isinstance(audio_url, str)
        and audio_url.startswith("https://")
        and len(audio_url) <= MAX_AUDIO_URL_CHARS
    ):
        raise MediaRefused("episode_not_found")
    extension = item.get("episodeFileExtension")
    if extension is not None and str(extension).lower() != "mp3":
        raise MediaRefused("unsupported_audio")  # missing: the audio head decides (5R11)
    millis = _int(item.get("trackTimeMillis"))
    duration = round(millis / 1000) if millis else 0  # 0: unknown, estimated at the head
    if duration and duration < MIN_DURATION_S:
        raise MediaRefused("no_speech")
    if duration > settings.media_max_audio_s:
        raise MediaRefused("too_long")
    title = str(item.get("trackName") or "").strip()[:MAX_TITLE_CHARS]
    if not mostly_latin(title):
        raise MediaRefused("not_english")
    return MediaInfo(
        title=title or "Podcast episode",
        site=str(item.get("collectionName") or "Podcast").strip()[:MAX_SITE_CHARS],
        duration_s=duration,
        image=_https(item.get("artworkUrl600")),
        published=str(item.get("releaseDate") or "")[:32] or None,
        audio_url=audio_url,
    )


async def probe_audio(url: str, settings: Settings, fetcher: SafeFetcher) -> AudioProbe:
    """Ranged GET of the episode's first bytes through the SSRF guard: an MP3 frame, a known
    size within MEDIA_MAX_AUDIO_BYTES. Raises MediaRefused (remembered) or MediaUnavailable
    (a timeout, connection error, 5xx or 429: not remembered, 5R5)."""
    try:
        head = await fetcher.audio_head(url)
        if head.total_bytes is None:
            raise MediaRefused("unsupported_audio")
        if head.total_bytes > settings.media_max_audio_bytes:
            raise MediaRefused("too_long")
        data, tag = head.data, mp3.id3v2_size(head.data)
        if tag >= len(data):
            if tag >= head.total_bytes:
                raise MediaRefused("unsupported_audio")
            more = await fetcher.audio_head(head.final_url, start=tag, length=TAG_PROBE_BYTES)
            data = more.data
    except FetchError as exc:
        log.warning("audio head failed", extra={"error_code": exc.code, "status": exc.status})
        if is_transient(exc):
            raise MediaUnavailable("audio") from None
        raise MediaRefused("unsupported_audio") from None
    frame = mp3.first_frame(data)
    if frame is None:
        raise MediaRefused("unsupported_audio")
    return AudioProbe(head.final_url, head.total_bytes, frame.bitrate_kbps)


def estimated_duration_s(probe: AudioProbe) -> int:
    """From the first frame's bitrate, for an episode Apple gave no length for. The walk at
    transcribe measures it exactly before any model call."""
    return round(probe.total_bytes * 8 / (probe.bitrate_kbps * 1000))


def _int(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return None
