"""Web recommendations: provider interface, Tavily and YouTube adapters, cache and call cap.

Privacy rule: an outgoing query is built only from concept data: its label, its graph domain
(to disambiguate, e.g. "separation principle" in finance, not marine engineering) and a
format suffix (`build_query`). Nothing about the reader (uid, persona, history, the article
they're on) ever leaves the server, and API keys never reach the client. One exception (decision
69 B2): the story search sends a library (corpus) article's own title (`story_query`), shared by
every reader; never the title of a page a reader brought in.

Cost rule: every provider call counts against SEARCH_DAILY_CAP (YouTube search also against
its own smaller cap). Past the cap we refuse new calls and degrade to whatever is cached,
even if stale, the same way the LLM budget guard does.
"""

import asyncio
import html
import logging
import re
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

import httpx
from google.cloud import firestore

from app.config import Settings, get_settings
from app.recs.models import PODCAST_DOMAINS, Format, WebResult
from app.store.spend_repo import today_utc

log = logging.getLogger("app.recs.web")

TAVILY_URL = "https://api.tavily.com/search"
YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"

MAX_RESULTS = 5
# Bump when normalization changes, so cached entries made the old way count as stale.
CACHE_VERSION = 2
MAX_LABEL_CHARS = 80
MAX_SNIPPET_CHARS = 280
WORDS_PER_MINUTE = 230

QUERY_SUFFIX: dict[Format, str] = {
    "article": "explained",
    "video": "explained",
    "podcast": "podcast episode",
}
# Kept out of article results: they are other formats, served by their own provider.
NOT_ARTICLE_DOMAINS = ("youtube.com", "youtu.be", "vimeo.com", *PODCAST_DOMAINS)

BLOCKLIST_FILE = Path(__file__).with_name("blocklist.txt")


class SearchCapReached(Exception):
    """Daily search budget spent; callers degrade to cached results."""


# ---------------------------------------------------------------- query and filtering

_UNSAFE = re.compile(r"[^\w\s\-&'.,/()]+", re.UNICODE)


def build_query(label: str, fmt: Format, domain: str | None = None) -> str:
    """The whole outgoing query: concept label (cleaned), its graph domain, a format suffix."""
    clean = re.sub(r"\s+", " ", _UNSAFE.sub(" ", label)).strip()[:MAX_LABEL_CHARS]
    context = f" {domain}" if domain and domain.isalpha() else ""
    return f"{clean}{context} {QUERY_SUFFIX[fmt]}"


_WORD = re.compile(r"[a-z0-9]+")


def mentions(label: str, text: str) -> bool:
    """Relevance gate: the result's title or snippet names at least one real word of the
    concept (or its acronym), so an off-topic hit never reaches the reader."""

    def stem(w: str) -> str:
        return w[:-1] if len(w) > 3 and w.endswith("s") else w

    words = {stem(w) for w in _WORD.findall(label.casefold()) if len(w) > 3}
    words |= {stem(w.casefold()) for w in re.findall(r"\b[A-Z]{2,6}s?\b", label)}
    haystack = {stem(w) for w in _WORD.findall(text.casefold())}
    return bool(words & haystack) if words else True


# ---------------------------------------------------------------- story search (decision 69 B2)

STORY = "story"  # counter of calls made for the end-of-article story search
STORY_FORMATS: tuple[Format, ...] = ("article", "video")
MAX_STORY_CHARS = 120
_STOP = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "have",
        "how",
        "in",
        "into",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "that",
        "the",
        "their",
        "this",
        "to",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
        "after",
        "over",
        "says",
        "said",
        "new",
    ]
)


def story_key(content_id: str) -> str:
    return f"story:{content_id}"


def story_query(title: str) -> str:
    """The whole outgoing query: a corpus article's title, cleaned. Never reader data, never a
    page a reader brought in (DESIGN §16.3)."""
    return re.sub(r"\s+", " ", _UNSAFE.sub(" ", title)).strip()[:MAX_STORY_CHARS]


def title_words(title: str) -> frozenset[str]:
    return frozenset(w for w in _WORD.findall(title.casefold()) if len(w) > 2 and w not in _STOP)


def story_relevant(result: WebResult, labels: Sequence[str], words: frozenset[str]) -> bool:
    """Names one of the article's top key ideas, or shares at least two distinctive title words."""
    text = f"{result.title} {result.snippet}"
    if any(mentions(label, text) for label in labels):
        return True
    return len(words & set(_WORD.findall(text.casefold()))) >= 2


def cache_key(query: str) -> str:
    return f"v{CACHE_VERSION}|{query}"


def load_blocklist(path: Path = BLOCKLIST_FILE) -> frozenset[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return frozenset(
        line.strip().lower() for line in lines if line.strip() and not line.startswith("#")
    )


def host_of(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host.removeprefix("www.")


def is_blocked(url: str, blocklist: Iterable[str]) -> bool:
    host = host_of(url)
    return any(host == d or host.endswith(f".{d}") for d in blocklist)


def is_web_url(url: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme in ("http", "https") and bool(parts.hostname)


def clip(text: str | None, limit: int = MAX_SNIPPET_CHARS) -> str:
    text = re.sub(r"\s+", " ", html.unescape(text or "")).strip()
    return text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0] + "…"


_ISO_DURATION = re.compile(r"^P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$")


def parse_iso_duration(value: str | None) -> int | None:
    """YouTube's ISO 8601 durations ("PT15M33S", "P1DT2H") → seconds."""
    match = _ISO_DURATION.match(value or "")
    if not match or not any(match.groups()):
        return None
    d, h, m, s = (int(g or 0) for g in match.groups())
    total = ((d * 24 + h) * 60 + m) * 60 + s
    return total or None  # live streams report P0D


# ---------------------------------------------------------------- providers


class SearchProvider(Protocol):
    name: str
    formats: frozenset[Format]

    async def search(
        self, query: str, fmt: Format, news: bool = False,
        include_domains: Sequence[str] = (),
    ) -> list[WebResult]: ...  # fmt: skip


class TavilyProvider:
    """Articles, and podcast episodes via include_domains. One credit per basic search."""

    name = "tavily"
    formats: frozenset[Format] = frozenset({"article", "podcast"})

    def __init__(
        self,
        api_key: str,
        blocklist: frozenset[str],
        timeout_s: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._key = api_key
        self._blocklist = blocklist
        self._timeout = timeout_s
        self._transport = transport

    async def search(
        self, query: str, fmt: Format, news: bool = False,
        include_domains: Sequence[str] = (),
    ) -> list[WebResult]:  # fmt: skip
        body: dict[str, object] = {
            "query": query,
            "search_depth": "basic",
            # The For you feed (M7.5) asks for recent news articles; Up next for explainers.
            "topic": "news" if news and fmt == "article" else "general",
            # The feed filters page shapes after the search, so it asks for more (same credit).
            "max_results": FEED_MAX_RESULTS if news else MAX_RESULTS,
            "include_images": True,  # per-result images where Tavily has them
            "include_published_date": True,
            "safe_search": True,
        }
        if news and fmt == "article":
            body["days"] = FEED_NEWS_DAYS
        feed_article = news and fmt == "article"
        if fmt == "podcast":
            body["include_domains"] = list(PODCAST_DOMAINS)
        elif feed_article and include_domains:
            # The feed's fallback (decision 50): top outlets and wires only, one constant list.
            body["include_domains"] = list(include_domains)
        elif not feed_article:
            body["exclude_domains"] = sorted({*NOT_ARTICLE_DOMAINS, *self._blocklist})[:150]
        # Feed articles: with `exclude_domains` the news topic returned section pages only
        # (9 results, 0 articles vs 8 without it, 2026-10-10), so those domains are dropped
        # here instead; the blocklist is applied to every result in WebSearch._filter.
        async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
            resp = await client.post(
                TAVILY_URL, json=body, headers={"Authorization": f"Bearer {self._key}"}
            )
            resp.raise_for_status()
            data = resp.json()
        out = []
        for r in data.get("results") or []:
            url = str(r.get("url") or "")
            if not is_web_url(url) or (feed_article and is_blocked(url, NOT_ARTICLE_DOMAINS)):
                continue
            words = len(str(r.get("raw_content") or r.get("content") or "").split())
            out.append(
                WebResult(
                    url=url,
                    title=clip(r.get("title"), 200) or host_of(url),
                    source=host_of(url),
                    format=fmt,
                    # Only a snippet comes back, so article length is unknown; podcasts too.
                    duration_or_read_time=None if words < 400 else words * 60 // WORDS_PER_MINUTE,
                    snippet=clip(r.get("content")),
                    # Only an image Tavily attached to this result; query-level images don't
                    # belong to any one result and were often unrelated.
                    thumbnail=_first_image(r.get("images")),
                    published_at=r.get("published_date") or None,
                )
            )
        return out


class YouTubeProvider:
    """Videos via the YouTube Data API v3: search.list, then videos.list for durations and the
    declared language (a video declared in another language is dropped, decision 64)."""

    name = "youtube"
    formats: frozenset[Format] = frozenset({"video"})

    def __init__(
        self, api_key: str, timeout_s: float, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._key = api_key
        self._timeout = timeout_s
        self._transport = transport

    async def search(
        self, query: str, fmt: Format, news: bool = False,
        include_domains: Sequence[str] = (),
    ) -> list[WebResult]:  # fmt: skip
        async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
            found = await client.get(
                YOUTUBE_SEARCH_URL,
                params={
                    "part": "snippet",
                    "q": query,
                    "type": "video",
                    "maxResults": MAX_RESULTS,
                    "safeSearch": "strict",
                    "relevanceLanguage": "en",
                    "key": self._key,
                    # The feed (M7.5) wants recent explainers, not Shorts or evergreen kids'
                    # lessons: 4–20 minutes, published in the last 30 days.
                    **(
                        {"videoDuration": "medium", "publishedAfter": _days_ago(FEED_VIDEO_DAYS)}
                        if news
                        else {}
                    ),
                },
            )
            found.raise_for_status()
            items = [i for i in found.json().get("items") or [] if i.get("id", {}).get("videoId")]
            if not items:
                return []
            ids = [i["id"]["videoId"] for i in items]
            details = await client.get(
                YOUTUBE_VIDEOS_URL,
                params={"part": "snippet,contentDetails", "id": ",".join(ids), "key": self._key},
            )
            details.raise_for_status()
        found_details = details.json().get("items") or []
        durations = {
            v.get("id"): parse_iso_duration(v.get("contentDetails", {}).get("duration"))
            for v in found_details
        }
        foreign = {v.get("id") for v in found_details if not declared_english(v.get("snippet"))}
        out = []
        for item in items:
            vid, snip = item["id"]["videoId"], item.get("snippet") or {}
            if vid in foreign:
                continue
            thumbs = snip.get("thumbnails") or {}
            thumb = (thumbs.get("medium") or thumbs.get("high") or thumbs.get("default") or {}).get(
                "url"
            )
            out.append(
                WebResult(
                    url=f"https://www.youtube.com/watch?v={vid}",
                    title=clip(snip.get("title"), 200) or "YouTube video",
                    source=snip.get("channelTitle") or "YouTube",
                    format="video",
                    duration_or_read_time=durations.get(vid),
                    snippet=clip(snip.get("description")),
                    thumbnail=thumb,
                    published_at=snip.get("publishedAt"),
                )
            )
        return out


def declared_english(snippet: object) -> bool:
    """A video's spoken (else metadata) language is English or not declared. Latin-script
    Hindi titles pass the title check, so this is the only signal for them."""
    snip = snippet if isinstance(snippet, dict) else {}
    language = snip.get("defaultAudioLanguage") or snip.get("defaultLanguage")
    return not language or str(language).lower().startswith("en")


def _days_ago(days: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _first_image(images: object) -> str | None:
    if isinstance(images, list) and images:
        first = images[0]
        url = first.get("url") if isinstance(first, dict) else first
        return url if isinstance(url, str) and is_web_url(url) else None
    return None


# ---------------------------------------------------------------- cache and call counter


class CachedResults:
    def __init__(self, results: list[WebResult], fetched_at: datetime, query: str = "") -> None:
        self.results = results
        self.fetched_at = fetched_at
        self.query = query  # an entry for a different query (e.g. after a change) is stale


class RecCacheStore(Protocol):
    """Per (concept_id, format). Concept-level public data, never per reader."""

    async def get(self, concept_id: str, fmt: Format) -> CachedResults | None: ...

    async def put(
        self, concept_id: str, fmt: Format, results: list[WebResult], query: str
    ) -> None: ...


ANONYMOUS = "anonymous"  # counter of calls triggered by anonymous (demo) readers
FEED = "feed"  # counter of calls made for the For you feed (M7.5), within FEED_SEARCH_DAILY_CAP
# Onboarding's concept searches (decision 41), a shared sub-cap within the feed's calls.
ONBOARDING_CONCEPT = "onboarding_concept"
FEED_NEWS_DAYS = 7
FEED_VIDEO_DAYS = 30
FEED_MAX_RESULTS = 10  # one credit; 15 timed out at 10 s and Tavily rarely returns more than 10


class SearchCallStore(Protocol):
    async def count_today(self, provider: str | None = None) -> int: ...

    async def add(
        self, provider: str, calls: int, anonymous: bool = False, feed: bool = False,
        extra: str | None = None,
    ) -> None: ...  # fmt: skip


class FirestoreRecCache:
    COLLECTION = "rec_cache"

    def __init__(self, project: str) -> None:
        self._db = firestore.AsyncClient(project=project or None)

    def _doc(self, concept_id: str, fmt: Format) -> firestore.AsyncDocumentReference:
        return self._db.collection(self.COLLECTION).document(f"{concept_id}__{fmt}")

    async def get(self, concept_id: str, fmt: Format) -> CachedResults | None:
        snap = await self._doc(concept_id, fmt).get()
        if not snap.exists:
            return None
        data = snap.to_dict() or {}
        return CachedResults(
            [WebResult.model_validate(r) for r in data.get("results", [])],
            datetime.fromisoformat(data["fetched_at"]),
            data.get("query", ""),
        )

    async def put(self, concept_id: str, fmt: Format, results: list[WebResult], query: str) -> None:
        await self._doc(concept_id, fmt).set(
            {
                "concept_id": concept_id,
                "format": fmt,
                "query": query,
                "results": [r.model_dump() for r in results],
                "fetched_at": datetime.now(UTC).isoformat(),
            }
        )


class FirestoreSearchCalls:
    """ops/search/days/{yyyy-mm-dd}: calls per provider, in total, and those triggered by
    anonymous readers (UTC)."""

    def __init__(self, project: str) -> None:
        self._db = firestore.AsyncClient(project=project or None)

    def _doc(self) -> firestore.AsyncDocumentReference:
        return (
            self._db.collection("ops").document("search").collection("days").document(today_utc())
        )

    async def count_today(self, provider: str | None = None) -> int:
        snap = await self._doc().get()
        data = (snap.to_dict() or {}) if snap.exists else {}
        return int(data.get(provider or "calls", 0))

    async def add(
        self, provider: str, calls: int, anonymous: bool = False, feed: bool = False,
        extra: str | None = None,
    ) -> None:  # fmt: skip
        fields = {
            "calls": firestore.Increment(calls),
            provider: firestore.Increment(calls),
            "updated_at": firestore.SERVER_TIMESTAMP,
        }
        if anonymous:
            fields[ANONYMOUS] = firestore.Increment(calls)
        if feed:
            fields[FEED] = firestore.Increment(calls)
        if extra:
            fields[extra] = firestore.Increment(calls)
        await self._doc().set(fields, merge=True)


class InMemoryRecCache:
    def __init__(self) -> None:
        self.entries: dict[tuple[str, str], CachedResults] = {}

    async def get(self, concept_id: str, fmt: Format) -> CachedResults | None:
        return self.entries.get((concept_id, fmt))

    async def put(self, concept_id: str, fmt: Format, results: list[WebResult], query: str) -> None:
        self.entries[(concept_id, fmt)] = CachedResults(results, datetime.now(UTC), query)


class InMemorySearchCalls:
    def __init__(self) -> None:
        self.calls: dict[str, int] = {}
        self.anonymous = 0
        self.feed = 0
        self.extra: dict[str, int] = {}

    async def count_today(self, provider: str | None = None) -> int:
        if provider == ANONYMOUS:
            return self.anonymous
        if provider == FEED:
            return self.feed
        if provider in self.extra:
            return self.extra[provider]
        if provider:
            return self.calls.get(provider, 0)
        return sum(self.calls.values())

    async def add(
        self, provider: str, calls: int, anonymous: bool = False, feed: bool = False,
        extra: str | None = None,
    ) -> None:  # fmt: skip
        self.calls[provider] = self.calls.get(provider, 0) + calls
        if anonymous:
            self.anonymous += calls
        if feed:
            self.feed += calls
        if extra:
            self.extra[extra] = self.extra.get(extra, 0) + calls


# ---------------------------------------------------------------- service


class WebSearch:
    """Cached, capped, de-duplicated lookups of web results per (concept, format)."""

    def __init__(
        self,
        providers: dict[Format, SearchProvider],
        cache: RecCacheStore,
        calls: SearchCallStore,
        settings: Settings,
        blocklist: frozenset[str],
    ) -> None:
        self._providers = providers
        self._cache = cache
        self._calls = calls
        self._settings = settings
        self._blocklist = blocklist
        self._inflight: dict[tuple[str, Format], asyncio.Task[list[WebResult]]] = {}
        self._reserve_lock = asyncio.Lock()

    @property
    def formats(self) -> frozenset[Format]:
        return frozenset(self._providers)

    async def cached(
        self, concept_id: str, fmt: Format, query: str | None = None
    ) -> tuple[list[WebResult], bool]:
        """(results, fresh). Stale entries are still returned; `fresh` says whether to refetch.
        An entry made for a different query than `query` counts as stale."""
        entry = await self._cache.get(concept_id, fmt)
        if entry is None:
            return [], False
        ttl = timedelta(hours=self._settings.recs_cache_ttl_h)
        fresh = datetime.now(UTC) - entry.fetched_at < ttl
        if query is not None and entry.query != cache_key(query):
            fresh = False
        return self._filter(entry.results), fresh

    def pending(self, concept_id: str, fmt: Format) -> bool:
        task = self._inflight.get((concept_id, fmt))
        return task is not None and not task.done()

    async def anonymous_allowance_left(self) -> bool:
        """Whether anonymous readers may still trigger uncached searches today."""
        used = await self._calls.count_today(ANONYMOUS)
        return used < self._settings.anon_search_daily_cap

    def refresh(
        self,
        concept_id: str,
        label: str,
        fmt: Format,
        domain: str | None = None,
        *,
        anonymous: bool = False,
    ) -> asyncio.Task[list[WebResult]]:
        """Start (or join) a background fetch; the caller doesn't wait for it."""
        key = (concept_id, fmt)
        task = self._inflight.get(key)
        if task is None or task.done():
            task = asyncio.create_task(
                self.fetch(concept_id, label, fmt, domain, anonymous=anonymous)
            )
            self._inflight[key] = task
        return task

    async def fetch(
        self,
        concept_id: str,
        label: str,
        fmt: Format,
        domain: str | None = None,
        *,
        anonymous: bool = False,
    ) -> list[WebResult]:
        provider = self._providers.get(fmt)
        if provider is None:
            return []
        calls = 2 if provider.name == "youtube" else 1  # search.list + videos.list
        try:
            # Check and reserve together, so concurrent lookups can't overshoot the cap.
            async with self._reserve_lock:
                await self._check_cap(provider.name, calls, anonymous)
                await self._calls.add(provider.name, calls, anonymous)
        except SearchCapReached:
            stale, _ = await self.cached(concept_id, fmt)
            return stale
        query = build_query(label, fmt, domain)
        try:
            results = await provider.search(query, fmt)
        except (httpx.HTTPError, ValueError) as exc:
            log.warning(
                "web search failed",
                extra={
                    "provider": provider.name,
                    "format": fmt,
                    "concept_id": concept_id,
                    "error": type(exc).__name__,
                },
            )
            stale, _ = await self.cached(concept_id, fmt)
            return stale
        clean = [r for r in self._filter(results) if mentions(label, f"{r.title} {r.snippet}")]
        await self._cache.put(concept_id, fmt, clean, cache_key(query))
        log.info(
            "web search",
            extra={
                "provider": provider.name,
                "format": fmt,
                "concept_id": concept_id,
                "results": len(clean),
                "dropped": len(results) - len(clean),
            },
        )
        return clean

    async def cached_entry(
        self, key: str, fmt: Format, query: str | None = None
    ) -> CachedResults | None:
        """A cache entry as stored (the feed keys entries by day, so it has no TTL). With
        `query`, an entry made for a different query (a changed phrase) counts as missing."""
        entry = await self._cache.get(key, fmt)
        if entry is not None and query is not None and entry.query != cache_key(query):
            return None
        return entry

    async def fetch_feed(
        self, key: str, fmt: Format, query: str, keep: Callable[[WebResult], bool],
        sub_cap: tuple[str, int] | None = None, include_domains: Sequence[str] = (),
    ) -> list[WebResult] | None:  # fmt: skip
        """One For you search (M7.5 §A): the feed's own cap, an optional shared sub-cap
        (counter, limit) and the global caps are checked and reserved together; results pass
        the blocklist and `keep` (topic relevance, dates) and are cached under `key`. None when
        a cap is spent or the provider failed. `include_domains` restricts article searches
        (decision 50's fallback)."""
        provider = self._providers.get(fmt)
        if provider is None:
            return []
        calls = 2 if provider.name == "youtube" else 1
        try:
            async with self._reserve_lock:
                used = await self._calls.count_today(FEED)
                if used + calls > self._settings.feed_search_daily_cap:
                    log.warning("feed search cap reached", extra={"feed_today": used})
                    raise SearchCapReached("daily feed search cap reached")
                if sub_cap is not None:
                    sub_used = await self._calls.count_today(sub_cap[0])
                    if sub_used + calls > sub_cap[1]:
                        log.warning("feed sub-cap reached", extra={"counter": sub_cap[0]})
                        raise SearchCapReached(f"daily {sub_cap[0]} cap reached")
                await self._check_cap(provider.name, calls, anonymous=False)
                extra = sub_cap[0] if sub_cap is not None else None
                await self._calls.add(provider.name, calls, feed=True, extra=extra)
        except SearchCapReached:
            return None
        try:
            if include_domains:
                results = await provider.search(
                    query, fmt, news=True, include_domains=include_domains
                )
            else:
                results = await provider.search(query, fmt, news=True)
        except (httpx.HTTPError, ValueError) as exc:
            error = type(exc).__name__
            extra = {"provider": provider.name, "format": fmt, "error": error}
            log.warning("feed search failed", extra=extra)
            return None
        clean = [r for r in self._filter(results) if keep(r)]
        await self._cache.put(key, fmt, clean, cache_key(query))
        dropped = len(results) - len(clean)
        log.info(
            "feed search",
            extra={"provider": provider.name, "format": fmt, "key": key, "results": len(clean),
                   "dropped": dropped},
        )  # fmt: skip
        return clean

    def refresh_story(
        self, content_id: str, title: str, fmt: Format, keep: Callable[[WebResult], bool],
        *, anonymous: bool = False,
    ) -> asyncio.Task[list[WebResult] | None]:  # fmt: skip
        """Start (or join) one background story search for a corpus article; never waited on."""
        key = (story_key(content_id), fmt)
        task = self._inflight.get(key)
        if task is None or task.done():
            task = asyncio.create_task(
                self.fetch_story(content_id, title, fmt, keep, anonymous=anonymous)
            )
            self._inflight[key] = task
        return task

    async def fetch_story(
        self, content_id: str, title: str, fmt: Format, keep: Callable[[WebResult], bool],
        *, anonymous: bool = False,
    ) -> list[WebResult] | None:  # fmt: skip
        """One story search: its own cap plus the global, YouTube and anonymous ones (never the
        feed's), checked and reserved together. Stored even when empty, so it never runs twice;
        None (nothing stored) when a cap is spent or the provider failed."""
        provider = self._providers.get(fmt)
        if provider is None:
            return None
        calls = 2 if provider.name == "youtube" else 1
        try:
            async with self._reserve_lock:
                used = await self._calls.count_today(STORY)
                if used + calls > self._settings.story_search_daily_cap:
                    log.warning("story search cap reached", extra={"story_today": used})
                    raise SearchCapReached("daily story search cap reached")
                await self._check_cap(provider.name, calls, anonymous)
                await self._calls.add(provider.name, calls, anonymous, extra=STORY)
        except SearchCapReached:
            return None
        query = story_query(title)
        try:
            results = await provider.search(query, fmt, news=fmt == "article")
        except (httpx.HTTPError, ValueError) as exc:
            log.warning(
                "story search failed",
                extra={"provider": provider.name, "format": fmt, "error": type(exc).__name__},
            )
            return None
        clean = [r for r in self._filter(results) if keep(r)]
        await self._cache.put(story_key(content_id), fmt, clean, cache_key(query))
        log.info(
            "story search",
            extra={"provider": provider.name, "format": fmt, "content_id": content_id,
                   "results": len(clean), "dropped": len(results) - len(clean)},
        )  # fmt: skip
        return clean

    async def _check_cap(self, provider: str, calls: int = 1, anonymous: bool = False) -> None:
        if anonymous:
            used = await self._calls.count_today(ANONYMOUS)
            if used + calls > self._settings.anon_search_daily_cap:
                log.warning("anonymous search cap reached", extra={"anonymous_today": used})
                raise SearchCapReached("daily anonymous search cap reached")
        total = await self._calls.count_today()
        if total >= self._settings.search_daily_cap:  # attempted calls, failures included
            log.warning("search cap reached", extra={"calls_today": total})
            raise SearchCapReached(f"daily search cap {self._settings.search_daily_cap} reached")
        if provider == "youtube":
            yt = await self._calls.count_today("youtube")
            if yt + 2 > self._settings.youtube_search_daily_cap * 2:  # 2 calls per search
                log.warning("youtube search cap reached", extra={"calls_today": yt})
                raise SearchCapReached("daily YouTube search cap reached")

    def _filter(self, results: list[WebResult]) -> list[WebResult]:
        seen: set[str] = set()
        out = []
        for r in results:
            if is_blocked(r.url, self._blocklist) or r.url in seen:
                continue
            seen.add(r.url)
            out.append(r)
        return out


_service: WebSearch | None = None


def build_service(settings: Settings | None = None) -> WebSearch:
    settings = settings or get_settings()
    blocklist = load_blocklist()
    providers: dict[Format, SearchProvider] = {}
    tavily_key = settings.tavily_api_key.get_secret_value()
    youtube_key = settings.youtube_api_key.get_secret_value()
    if tavily_key:
        tavily = TavilyProvider(tavily_key, blocklist, settings.search_timeout_s)
        providers["article"] = providers["podcast"] = tavily
    if youtube_key:
        providers["video"] = YouTubeProvider(youtube_key, settings.search_timeout_s)
    log.info(
        "web search providers",
        extra={"tavily": bool(tavily_key), "youtube": bool(youtube_key)},
    )
    return WebSearch(
        providers,
        FirestoreRecCache(settings.db_project),
        FirestoreSearchCalls(settings.db_project),
        settings,
        blocklist,
    )


def get_web_search() -> WebSearch:
    global _service
    if _service is None:
        _service = build_service()
    return _service


def set_web_search(service: WebSearch | None) -> None:
    global _service
    _service = service
