"""The twice-daily outlet collection (decision 50). Knows no reader; no LLM, no search API.

Every registry section feed is fetched once per run through `safe_fetch` (feed content types,
its size cap, robots.txt), parsed from those bytes in a thread, filtered to the outlet's fresh
English article pages, and merged into one `rec_cache/outlets:<topic>` doc per topic. An outlet
whose feeds for a topic all failed keeps its previous list.
"""

import asyncio
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from app.graph.taxonomy import DOMAIN_IDS
from app.ingest.safe_fetch import FetchError
from app.recs.models import WebResult
from app.recs.outlet_feed import FEED_TYPES, FeedEntry, on_hosts, outlet_items, parse_entries
from app.recs.outlets import REGISTRY, Outlet, feed_urls
from app.store.outlet_repo import OutletStore

log = logging.getLogger("app.recs.outlets")

FETCH_CONCURRENCY = 8


class Fetcher(Protocol):
    async def fetch(self, url: str, *, content_types: frozenset[str] = ...) -> Any: ...


@dataclass
class CollectReport:
    feeds_ok: int = 0
    feeds_failed: list[str] = field(default_factory=list)  # "code url"
    fresh: dict[str, dict[str, int]] = field(default_factory=dict)  # topic → outlet → new items
    stored: dict[str, dict[str, int]] = field(default_factory=dict)  # topic → outlet → stored


def _feed_outlet(url: str) -> Outlet | None:
    return next((o for o in REGISTRY if any(url in urls for urls in o.sections.values())), None)


async def fetch_feeds(
    fetcher: Fetcher, urls: Sequence[str], report: CollectReport
) -> dict[str, list[FeedEntry]]:
    """url → parsed entries, for the feeds that answered; failures are recorded."""
    sem = asyncio.Semaphore(FETCH_CONCURRENCY)

    async def one(url: str) -> tuple[str, list[FeedEntry] | None]:
        outlet = _feed_outlet(url)
        if outlet is None or not on_hosts(url, outlet.feed_hosts):
            report.feeds_failed.append(f"not_registered {url}")
            return url, None
        async with sem:
            try:
                page = await fetcher.fetch(url, content_types=FEED_TYPES)
            except FetchError as exc:
                report.feeds_failed.append(f"{exc.code} {url}")
                return url, None
        try:
            return url, await asyncio.to_thread(parse_entries, page.body)
        except Exception as exc:  # a malformed feed fails alone
            report.feeds_failed.append(f"parse_{type(exc).__name__} {url}")
            return url, None

    results = await asyncio.gather(*(one(u) for u in urls))
    parsed = {u: entries for u, entries in results if entries is not None}
    report.feeds_ok = len(parsed)
    return parsed


def topic_items(
    topic: str, parsed: Mapping[str, list[FeedEntry]], now: datetime
) -> dict[str, list[WebResult]]:
    """outlet → this run's items for the topic; outlets whose feeds for it all failed are left
    out (so they keep their previous list)."""
    out: dict[str, list[WebResult]] = {}
    for outlet in REGISTRY:
        urls = outlet.sections.get(topic, ())
        answered = [u for u in urls if u in parsed]
        if answered:
            entries = (e for u in answered for e in parsed[u])
            out[outlet.id] = outlet_items(outlet, entries, now, topic)
    return out


async def collect(fetcher: Fetcher, store: OutletStore, now: datetime) -> CollectReport:
    report = CollectReport()
    parsed = await fetch_feeds(fetcher, feed_urls(), report)
    for topic in DOMAIN_IDS:
        fresh = topic_items(topic, parsed, now)
        if not any(topic in o.sections for o in REGISTRY):
            continue
        report.fresh[topic] = {oid: len(items) for oid, items in fresh.items()}
        report.stored[topic] = await store.merge_topic(topic, fresh, now)
    log.info(
        "outlet collection",
        extra={
            "feeds_ok": report.feeds_ok,
            "feeds_failed": len(report.feeds_failed),
            "items_stored": sum(n for t in report.stored.values() for n in t.values()),
        },
    )
    return report
