"""M2 part A: gather the corpus URL list (~220 business/economy news + ~70 Wikipedia explainers).

Run: cd apps/api && uv run python -m scripts.collect_corpus
Writes data/corpus_urls.txt ("url<TAB>source" per line) and data/wikipedia_qids.json.

Every request goes through SafeFetcher, so robots.txt is honoured for our agent. A source whose
feeds or sample articles answer 403 or are robots-disallowed is skipped entirely. Wikipedia's
robots.txt disallows its APIs (/w/, /api/), so titles are resolved from the article pages.
"""

import asyncio
import calendar
import json
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit, urlunsplit

import feedparser

from app.ingest.safe_fetch import FetchError, SafeFetcher
from app.ingest.urls import normalize_url

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
CORPUS_FILE = DATA_DIR / "corpus_urls.txt"
QIDS_FILE = DATA_DIR / "wikipedia_qids.json"

NEWS_TARGET = 220
WIKI_TARGET = 70
PROBE_ARTICLES = 2
SAMPLES_SHOWN = 5
WIKI_CONCURRENCY = 4
FEED_TYPES = frozenset(
    {"application/rss+xml", "application/atom+xml", "application/xml", "text/xml"}
)


@dataclass(frozen=True)
class Source:
    tag: str
    feeds: tuple[str, ...]
    path_prefixes: tuple[str, ...]  # an article URL's path must start with one of these


SOURCES: tuple[Source, ...] = (
    Source(
        "mint",
        tuple(
            f"https://www.livemint.com/rss/{s}"
            for s in ("economy", "markets", "companies", "money")
        ),
        ("/economy/", "/market/", "/companies/", "/money/", "/politics/policy/"),
    ),
    Source(
        "businessline",
        tuple(
            f"https://www.thehindubusinessline.com/{s}/feeder/default.rss"
            for s in ("economy", "economy/policy", "markets", "money-and-banking", "companies")
        ),
        ("/economy/", "/markets/", "/money-and-banking/", "/companies/"),
    ),
    Source(
        "business_standard",
        tuple(
            f"https://www.business-standard.com/rss/{s}.rss"
            for s in ("economy-102", "markets-106", "companies-101", "finance-103")
        ),
        ("/economy/", "/markets/", "/companies/", "/finance/"),
    ),
    Source(
        "et",
        tuple(
            f"https://economictimes.indiatimes.com/{s}"
            for s in (
                "news/economy/rssfeeds/1373380680.cms",
                "news/economy/policy/rssfeeds/1106944246.cms",
                "markets/rssfeeds/1977021501.cms",
            )
        ),
        ("/news/economy/", "/markets/"),
    ),
    Source(
        "bbc",
        tuple(
            f"https://feeds.bbci.co.uk/news/business/{s}rss.xml"
            for s in ("", "economy/", "companies/")
        ),
        ("/news/articles/",),
    ),
    Source(
        "guardian",
        tuple(
            f"https://www.theguardian.com/{s}/rss"
            for s in (
                "uk/business",
                "business/economics",
                "business/stock-markets",
                "business/banking",
                "business/retail",
            )
        ),
        ("/business/",),
    ),
)

# Formats that aren't a readable article, and paywalled or tip sections.
PATH_DENY = (
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
    "/prime/",
    "/portfolio/",
    "/recos/",
    "/quiz",
    "/newsletters/",
    "/sport",
    "/people/",
    "/entertainment/",
)
TITLE_DENY = re.compile(
    r"\b(cricket|football|ipl|horoscope|celebrit\w*|bollywood|box office|recipe|quiz|crossword"
    r"|bank holidays|summit|in pictures|watch|video|photos|live"
    r"|stocks? to buy|buy or sell|target price)\b",
    re.IGNORECASE,
)

# Priority order: the first WIKI_TARGET that resolve to distinct, non-disambiguation pages are kept.
WIKI_TITLES = (
    "Inflation",
    "Consumer price index",
    "Wholesale price index",
    "Core inflation",
    "Repurchase agreement",
    "Monetary policy",
    "Central bank",
    "Interest rate",
    "Inflation targeting",
    "Monetary Policy Committee (India)",
    "Reserve Bank of India",
    "Yield (finance)",
    "Yield curve",
    "Bond (finance)",
    "Government bond",
    "Government budget balance",
    "Fiscal policy",
    "Current account (balance of payments)",
    "Balance of payments",
    "Balance of trade",
    "Gross domestic product",
    "Gross value added",
    "Foreign exchange reserves",
    "Currency appreciation and depreciation",
    "Exchange rate",
    "Indian rupee",
    "Quantitative easing",
    "Stagflation",
    "Deflation",
    "Recession",
    "Purchasing Managers' Index",
    "Index of industrial production",
    "Goods and Services Tax (India)",
    "Tariff",
    "Foreign direct investment",
    "Foreign portfolio investment",
    "Non-performing asset",
    "Basis point",
    "Market capitalization",
    "Price–earnings ratio",
    "Initial public offering",
    "Mutual fund",
    "Derivative (finance)",
    "Futures contract",
    "Option (finance)",
    "Dividend",
    "Earnings before interest, taxes, depreciation and amortization",
    "Cash reserve ratio",
    "Statutory liquidity ratio",
    "Open market operation",
    "Money supply",
    "Government debt",
    "Sovereign credit rating",
    "Credit rating agency",
    "Securities and Exchange Board of India",
    "Stock market index",
    "BSE SENSEX",
    "NIFTY 50",
    "Federal Reserve",
    "Real interest rate",
    "Real versus nominal value (economics)",
    "Unemployment",
    "Phillips curve",
    "Purchasing power parity",
    "Capital account",
    "Twin deficits hypothesis",
    "Crowding out (economics)",
    "Fiscal multiplier",
    "Austerity",
    "Stimulus (economics)",
    "Subsidy",
    "Disinvestment",
    "Capital expenditure",
    "Working capital",
    "Return on equity",
    "Earnings per share",
    "Leverage (finance)",
    "Market trend",
    "Volatility (finance)",
    "Hedge (finance)",
    "Exchange-traded fund",
    "Private equity",
    "Venture capital",
    "Minimum support price (India)",
)


# ---------------------------------------------------------------- pure helpers


@dataclass(frozen=True)
class Item:
    source: str
    feed_index: int
    published: float  # epoch seconds, 0 if unknown
    url: str  # canonical
    title: str


def canonical(url: str) -> str:
    """News article ids live in the path, so query and fragment are tracking noise."""
    parts = urlsplit(url.strip())
    return normalize_url(urlunsplit((parts.scheme, parts.netloc, parts.path, "", "")))


def is_relevant(source: Source, url: str, title: str) -> bool:
    path = urlsplit(url).path.lower()
    if not path.startswith(source.path_prefixes):
        return False
    if any(token in path for token in PATH_DENY):
        return False
    return bool(title.strip()) and not TITLE_DENY.search(title)


def parse_feed(source: Source, feed_index: int, body: bytes) -> list[Item]:
    parsed = feedparser.parse(body)
    items = []
    for entry in parsed.entries:
        link, title = entry.get("link", ""), entry.get("title", "")
        if not link.startswith(("http://", "https://")):
            continue
        stamp = entry.get("published_parsed") or entry.get("updated_parsed")
        published = float(calendar.timegm(stamp)) if stamp else 0.0
        url = canonical(link)
        if is_relevant(source, url, title):
            items.append(Item(source.tag, feed_index, published, url, title.strip()))
    return items


def interleave(items: Iterable[Item]) -> list[Item]:
    """Newest first within each feed, round-robin across feeds, first occurrence of a URL wins."""
    by_feed: dict[int, list[Item]] = {}
    for item in items:
        by_feed.setdefault(item.feed_index, []).append(item)
    queues = [sorted(v, key=lambda i: -i.published) for _, v in sorted(by_feed.items())]
    out: list[Item] = []
    seen: set[str] = set()
    for rank in range(max((len(q) for q in queues), default=0)):
        for queue in queues:
            if rank < len(queue) and queue[rank].url not in seen:
                seen.add(queue[rank].url)
                out.append(queue[rank])
    return out


def allocate(available: dict[str, int], target: int) -> dict[str, int]:
    """Split `target` as evenly as possible; a source's shortfall goes to sources with surplus."""
    quota = dict.fromkeys(available, 0)
    remaining = target
    open_sources = [s for s in available if available[s] > 0]
    while remaining > 0 and open_sources:
        share, extra = divmod(remaining, len(open_sources))
        for i, s in enumerate(open_sources):
            want = share + (1 if i < extra else 0)
            take = min(want, available[s] - quota[s])
            quota[s] += take
            remaining -= take
        open_sources = [s for s in open_sources if quota[s] < available[s]]
        if share == 0 and extra == 0:
            break
    return quota


_QID = re.compile(r'"wgWikibaseItemId":"(Q\d+)"')
_CANONICAL = re.compile(r'<link rel="canonical" href="([^"]+)"')
_DISAMBIG = re.compile(r'"wgCategories":\[[^\]]*Disambiguation pages')


@dataclass(frozen=True)
class WikiPage:
    url: str
    title: str
    qid: str | None


def parse_wiki_page(html: str) -> WikiPage | None:
    """None for disambiguation pages or pages without a canonical link."""
    match = _CANONICAL.search(html)
    if not match or _DISAMBIG.search(html):
        return None
    url = canonical(match.group(1))
    title = urlsplit(url).path.removeprefix("/wiki/")
    qid = _QID.search(html)
    return WikiPage(url, title_from_path(title), qid.group(1) if qid else None)


def title_from_path(path_title: str) -> str:
    return unquote(path_title).replace("_", " ")


def wiki_url(title: str) -> str:
    return "https://en.wikipedia.org/wiki/" + quote(title.replace(" ", "_"), safe="(),'")


# ---------------------------------------------------------------- network


@dataclass
class SourceResult:
    source: Source
    items: list[Item] = field(default_factory=list)
    skipped: str | None = None  # reason the whole source was dropped
    notes: list[str] = field(default_factory=list)


async def collect_source(fetcher: SafeFetcher, source: Source) -> SourceResult:
    result = SourceResult(source)
    collected: list[Item] = []
    for index, feed in enumerate(source.feeds):
        try:
            page = await fetcher.fetch(feed, content_types=FEED_TYPES)
        except FetchError as exc:
            if exc.status == 403 or exc.code == "robots_disallowed":
                result.skipped = f"feed {feed}: {exc.code} {exc.status or ''}".strip()
                return result
            result.notes.append(f"feed skipped ({exc.code}): {feed}")
            continue
        collected.extend(parse_feed(source, index, page.body))
    allowed = [i for i in interleave(collected) if await fetcher.robots_allowed(i.url)]
    if not allowed:
        result.skipped = "no relevant articles in feeds"
        return result
    for item in allowed[:PROBE_ARTICLES]:
        try:
            await fetcher.fetch(item.url)
        except FetchError as exc:
            if exc.status == 403 or exc.code == "robots_disallowed":
                result.skipped = f"article probe: {exc.code} {exc.status or ''}".strip()
                return result
            result.notes.append(f"probe failed ({exc.code}): {item.url}")
    result.items = allowed
    return result


async def resolve_wiki(fetcher: SafeFetcher) -> tuple[list[WikiPage], list[str]]:
    sem = asyncio.Semaphore(WIKI_CONCURRENCY)

    async def one(title: str) -> WikiPage | str:
        async with sem:
            try:
                page = await fetcher.fetch(wiki_url(title))
            except FetchError as exc:
                return f"{title}: {exc.code} {exc.status or ''}".strip()
        parsed = parse_wiki_page(page.body.decode(page.encoding or "utf-8", errors="replace"))
        return parsed or f"{title}: disambiguation or no canonical link"

    results = await asyncio.gather(*(one(t) for t in WIKI_TITLES))
    pages: list[WikiPage] = []
    problems: list[str] = []
    seen: set[str] = set()
    for title, res in zip(WIKI_TITLES, results, strict=True):
        if isinstance(res, str):
            problems.append(res)
        elif res.url in seen:
            problems.append(f"{title}: duplicate of {res.title}")
        else:
            seen.add(res.url)
            pages.append(res)
    return pages[:WIKI_TARGET], problems


# ---------------------------------------------------------------- output


def write_outputs(news: dict[str, list[Item]], wiki: list[WikiPage]) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    counts = {s: len(v) for s, v in news.items()} | {"wikipedia": len(wiki)}
    lines = [
        f"# ReadLayer M2 corpus, collected {datetime.now(UTC).date().isoformat()}",
        "# format: url<TAB>source  counts: " + ", ".join(f"{k}={v}" for k, v in counts.items()),
    ]
    lines += [f"{i.url}\t{src}" for src, items in news.items() for i in items]
    lines += [f"{p.url}\twikipedia" for p in wiki]
    CORPUS_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    QIDS_FILE.write_text(
        json.dumps({p.url: {"title": p.title, "qid": p.qid} for p in wiki}, indent=1) + "\n",
        encoding="utf-8",
    )


def print_report(
    results: list[SourceResult],
    news: dict[str, list[Item]],
    wiki: list[WikiPage],
    wiki_problems: list[str],
) -> None:
    print("\n=== Sources ===")
    for r in results:
        tag = r.source.tag
        if r.skipped:
            print(f"{tag:18} SKIPPED: {r.skipped}")
        else:
            print(f"{tag:18} relevant={len(r.items):3}  selected={len(news.get(tag, [])):3}")
        for note in r.notes:
            print(f"{'':18} note: {note}")
    print(f"{'wikipedia':18} selected={len(wiki):3}")
    total = sum(len(v) for v in news.values())
    print(f"\nnews total={total}  wikipedia={len(wiki)}  all={total + len(wiki)}")
    for tag, items in news.items():
        print(f"\n--- {tag} samples ---")
        for i in items[:SAMPLES_SHOWN]:
            print(f"  {i.url}\n      {i.title}")
    print("\n--- wikipedia samples ---")
    for p in wiki[:SAMPLES_SHOWN]:
        print(f"  {p.url}  ({p.qid})")
    if wiki_problems:
        print("\nwikipedia titles dropped: " + "; ".join(wiki_problems))
    print(f"\nwrote {CORPUS_FILE} and {QIDS_FILE}")


async def main() -> int:
    fetcher = SafeFetcher()
    results = await asyncio.gather(*(collect_source(fetcher, s) for s in SOURCES))
    usable = {r.source.tag: r.items for r in results if not r.skipped}
    quota = allocate({s: len(v) for s, v in usable.items()}, NEWS_TARGET)
    news = {s: items[: quota[s]] for s, items in usable.items()}
    wiki, wiki_problems = await resolve_wiki(fetcher)
    write_outputs(news, wiki)
    print_report(results, news, wiki, wiki_problems)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
