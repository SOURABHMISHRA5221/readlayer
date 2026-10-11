"""RSS/Atom parsing for the outlet feeds (decision 50) and the M2 corpus script. Pure: no I/O.

`feedparser` only ever receives bytes that `safe_fetch` already fetched with one of FEED_TYPES
(never a URL, so it can't fetch anything itself). Item links are canonicalised before dedupe
(query and fragment are tracking noise on news sites).
"""

import calendar
import html
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit, urlunsplit

import feedparser

from app.ingest.urls import normalize_url
from app.recs.feed_rank import HUB_SEGMENTS, mostly_latin
from app.recs.models import WebResult
from app.recs.outlets import Outlet
from app.recs.web_search import clip, is_web_url

FEED_TYPES = frozenset(
    {"application/rss+xml", "application/atom+xml", "application/xml", "text/xml"}
)
# Formats that aren't a readable article (path substrings; shared with the corpus script).
MEDIA_DENY = (
    "/video",
    "/photo",
    "/podcast",
    "/gallery",
    "/slideshow",
    "/web-stories/",
    "/live/",
    "liveblog",
    "live-blog",
    "live-updates",
    "/quiz",
    "/newsletters/",
)
# Whole path segments of live blogs, video and audio pages (BBC /av/, Guardian /live/).
MEDIA_SEGMENTS = frozenset({"live", "video", "videos", "audio", "av", "podcasts"})
MAX_ITEM_AGE = timedelta(days=3)
CLOCK_SKEW = timedelta(hours=1)  # an outlet's clock slightly ahead of ours
ITEMS_PER_OUTLET = 20  # newest kept per (outlet, topic)
_TAGS = re.compile(r"<[^>]+>")


def canonical(url: str) -> str:
    """News article ids live in the path, so query and fragment are tracking noise."""
    parts = urlsplit(url.strip())
    return normalize_url(urlunsplit((parts.scheme, parts.netloc, parts.path, "", "")))


@dataclass(frozen=True)
class FeedEntry:
    url: str  # canonical
    title: str
    summary: str  # tags stripped, unescaped, clipped
    published: datetime | None
    thumbnail: str | None


def _published(entry: dict) -> datetime | None:
    stamp = entry.get("published_parsed") or entry.get("updated_parsed")
    return datetime.fromtimestamp(calendar.timegm(stamp), UTC) if stamp else None


def _thumbnail(entry: dict) -> str | None:
    for key in ("media_thumbnail", "media_content"):
        for media in entry.get(key) or []:
            url = media.get("url") if isinstance(media, dict) else None
            if isinstance(url, str) and url.startswith("https://") and is_web_url(url):
                return url
    return None


def summary_text(raw: str | None) -> str:
    """Tags stripped first, then entities unescaped (so an escaped tag stays text), clipped."""
    return clip(html.unescape(_TAGS.sub(" ", raw or "")))


def parse_entries(body: bytes) -> list[FeedEntry]:
    """Every entry with an http(s) link and a title, in feed order."""
    if not isinstance(body, bytes):  # never a URL or a path: feedparser would fetch it
        raise TypeError("parse_entries takes the fetched bytes")
    out = []
    for entry in feedparser.parse(body).entries:
        link, title = entry.get("link", ""), (entry.get("title") or "").strip()
        if not link.startswith(("http://", "https://")) or not title:
            continue
        out.append(
            FeedEntry(
                canonical(link),
                clip(html.unescape(title), 200),
                summary_text(entry.get("summary")),
                _published(entry),
                _thumbnail(entry),
            )
        )
    return out


def on_hosts(url: str, hosts: Iterable[str]) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return any(host == h or host.endswith(f".{h}") for h in hosts)


def outlet_article(url: str) -> bool:
    """An article page: https, at least two path segments, no hub, live, video or audio
    segment, no media path. (Outlet ids are opaque, e.g. BBC's /news/articles/c620r33plgppo,
    so the search results' slug rule doesn't apply here.)"""
    parts = urlsplit(url)
    segments = [s for s in parts.path.casefold().split("/") if s]
    if parts.scheme != "https" or len(segments) < 2:
        return False
    if HUB_SEGMENTS.intersection(segments) or MEDIA_SEGMENTS.intersection(segments):
        return False
    return not any(token in parts.path.casefold() for token in MEDIA_DENY)


def fresh(when: datetime | None, now: datetime) -> bool:
    """Dated within MAX_ITEM_AGE (undated items are dropped: they can't be shown as news)."""
    return when is not None and -CLOCK_SKEW <= now - when <= MAX_ITEM_AGE


def outlet_items(outlet: Outlet, entries: Iterable[FeedEntry], now: datetime) -> list[WebResult]:
    """Entries that are this outlet's fresh, English article pages, as feed results."""
    out = []
    for e in entries:
        if not on_hosts(e.url, outlet.article_hosts) or not outlet_article(e.url):
            continue
        if not fresh(e.published, now) or not mostly_latin(e.title):
            continue
        out.append(
            WebResult(
                url=e.url,
                title=e.title,
                source=outlet.name,
                format="article",
                snippet=e.summary,
                thumbnail=e.thumbnail,
                published_at=e.published.isoformat() if e.published else None,
            )
        )
    return out


def _when(r: WebResult) -> datetime | None:
    return datetime.fromisoformat(r.published_at) if r.published_at else None


def merge(
    previous: Sequence[WebResult], new: Sequence[WebResult], now: datetime
) -> list[WebResult]:
    """One (outlet, topic) list after a run: new and previous items, one per canonical URL (the
    newer copy wins), re-filtered by age, newest first, at most ITEMS_PER_OUTLET."""
    by_url: dict[str, WebResult] = {}
    for r in [*previous, *new]:
        r = r.model_copy(update={"url": canonical(r.url)})
        by_url[r.url] = r
    kept = [r for r in by_url.values() if fresh(_when(r), now)]  # all dated after this
    return sorted(kept, key=lambda r: (_when(r), r.url), reverse=True)[:ITEMS_PER_OUTLET]
