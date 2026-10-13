"""Which links are recordings, and their canonical form (Media plan §A). Pure: no I/O.

Every spelling of the same recording maps to one canonical URL, so one transcript serves all
of them: `content_id = url_hash(canonical)`. Anything not recognised here is an article.
"""

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

from app.ingest.urls import normalize_url, url_hash

_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_DIGITS = re.compile(r"^\d{1,20}$")
_APPLE_SHOW = re.compile(r"/id(\d{1,20})/?$")
YOUTUBE_HOSTS = frozenset({"youtube.com", "www.youtube.com", "m.youtube.com"})
YOUTUBE_SHORT_HOST = "youtu.be"
APPLE_HOST = "podcasts.apple.com"


@dataclass(frozen=True)
class YouTube:
    video_id: str

    @property
    def canonical(self) -> str:
        return f"https://www.youtube.com/watch?v={self.video_id}"


@dataclass(frozen=True)
class ApplePodcast:
    show_id: str
    episode_id: str | None  # None: a show page, refused with `not_an_episode`

    @property
    def canonical(self) -> str:
        base = f"https://podcasts.apple.com/podcast/id{self.show_id}"
        return f"{base}?i={self.episode_id}" if self.episode_id else base


@dataclass(frozen=True)
class AudioFile:
    url: str

    @property
    def canonical(self) -> str:
        return normalize_url(self.url)


Media = YouTube | ApplePodcast | AudioFile


def classify(url: str) -> Media | None:
    """The recording a link points to, or None for an article (or anything else)."""
    try:
        parts = urlsplit(url.strip())
        host = (parts.hostname or "").lower().rstrip(".")
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or parts.username or parts.password:
        return None
    if host in YOUTUBE_HOSTS or host == YOUTUBE_SHORT_HOST:
        video_id = _youtube_id(host, parts.path, parts.query)
        return YouTube(video_id) if video_id else None
    if host == APPLE_HOST:
        return _apple(parts.path, parts.query)
    if parts.scheme == "https" and parts.path.lower().endswith(".mp3"):
        return AudioFile(url.strip())
    return None


def content_id(media: Media) -> str:
    return url_hash(media.canonical)


def kind(media: Media) -> str:
    """The API's `kind` / library `format` for a recording."""
    return "video" if isinstance(media, YouTube) else "podcast"


def _youtube_id(host: str, path: str, query: str) -> str | None:
    segments = [s for s in path.split("/") if s]
    if host == YOUTUBE_SHORT_HOST:
        candidate = segments[0] if len(segments) == 1 else None
    elif segments == ["watch"]:
        values = parse_qs(query).get("v") or []
        candidate = values[0] if len(values) == 1 else None
    elif len(segments) == 2 and segments[0] in ("shorts", "embed"):
        candidate = segments[1]
    else:
        candidate = None
    return candidate if candidate and _VIDEO_ID.match(candidate) else None


def _apple(path: str, query: str) -> ApplePodcast | None:
    match = _APPLE_SHOW.search(path)
    if not match:
        return None
    episodes = parse_qs(query).get("i") or []
    if len(episodes) > 1 or (episodes and not _DIGITS.match(episodes[0])):
        return None
    return ApplePodcast(match.group(1), episodes[0] if episodes else None)
