"""Seed the demo personas' For you snapshots (M7.5 §A.8, decision 38).

    cd apps/api && uv run python -m scripts.seed_demo_feed --dry-run   # print, write no snapshot
    cd apps/api && uv run python -m scripts.seed_demo_feed            # write persona_feeds/*

For each persona's two topics, the same searches as the live feed (taxonomy label + fixed
phrase, day-keyed shared cache, the feed cap and the global caps): ≤ 6 topics × 3 formats =
≤ 18 searches (≤ 24 calls), counted in `ops/search`. The dry run performs those searches too
(they're cached, so the real run the same day pays nothing more) and writes no snapshot.
Every article is then checked locally (safe_fetch + extraction, ≥ 400 words; no LLM, no
Firestore write) and dropped if it fails, so a judge never hits a dead link. The 14-day date
filter applies here, never when a snapshot is served. Production write: 3 `persona_feeds/{p}`
docs (public search results only, no user data). No LLM.
"""

import argparse
import asyncio
import sys
from datetime import UTC, datetime

from app.config import get_settings
from app.graph.graph import ConceptGraph
from app.graph.loader import load_graph, set_graph
from app.ingest.extract import extract
from app.ingest.safe_fetch import FetchError, SafeFetcher
from app.log import configure_logging
from app.recs.feed import (
    PERSONA_TOPICS,
    FeedSearch,
    Snapshot,
    SnapshotRepo,
    feed_key,
)
from app.recs.models import WebResult
from app.recs.web_search import get_web_search
from app.store.docstore import get_doc_store
from app.store.spend_repo import today_utc

MIN_WORDS = 400


async def article_ok(fetcher: SafeFetcher, url: str) -> bool:
    try:
        page = await fetcher.fetch(url)
    except FetchError:
        return False
    html = page.body.decode(page.encoding, errors="replace") if page.encoding else page.body
    extracted = await asyncio.to_thread(extract, html, page.url)
    return sum(len(p.split()) for p in extracted.paragraphs) >= MIN_WORDS


async def build(persona: str, graph: ConceptGraph, search: FeedSearch, fetcher: SafeFetcher):
    topics = PERSONA_TOPICS[persona]
    now = datetime.now(UTC)
    await search.gather(list(topics), graph, now, wait_s=60.0)
    web = get_web_search()
    items: list[tuple[str, WebResult]] = []
    dropped = 0
    for topic in topics:
        for fmt in ("article", "video", "podcast"):
            entry = await web.cached_entry(feed_key(topic, today_utc()), fmt)
            for r in entry.results if entry else []:
                if fmt == "article" and not await article_ok(fetcher, r.url):
                    dropped += 1
                    continue
                items.append((topic, r))
    return Snapshot(persona, now.isoformat(timespec="seconds"), topics, tuple(items)), dropped


async def main(args: argparse.Namespace) -> int:
    configure_logging("WARNING")
    graph = await load_graph(get_settings().concepts_uri)
    set_graph(graph)
    search, fetcher, repo = (
        FeedSearch(get_web_search()),
        SafeFetcher(),
        SnapshotRepo(get_doc_store()),
    )
    for persona in PERSONA_TOPICS:
        snap, dropped = await build(persona, graph, search, fetcher)
        print(
            f"{persona}: topics {snap.topics}, {len(snap.items)} items, {dropped} articles dropped"
        )
        for topic, r in snap.items:
            print(f"  [{topic}/{r.format}] {r.title[:90]} — {r.url}")
        if not args.dry_run:
            await repo.put(snap)
            print(f"  wrote persona_feeds/{persona}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    sys.exit(asyncio.run(main(parser.parse_args())))
