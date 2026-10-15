"""Seed the demo personas' For you snapshots (M7.5 §A.8, decisions 38, 50, 51).

    cd apps/api && uv run python -m scripts.seed_demo_feed --dry-run   # print, write no snapshot
    cd apps/api && uv run python -m scripts.seed_demo_feed            # write persona_feeds/*
    (--persona newcomer limits it to one persona, e.g. on the emulator harness)

Articles come from the collected outlet entries (`rec_cache/outlets:<topic>`, written by the
collection job; run it first), offered as PERSONA_COUNTRY ("IN", decision 51) sees them: per
topic, local and global lists newest first, taken in a local, global, local pattern (60/40).
A topic short of outlet articles uses the same restricted fallback search as the live feed.
Videos and podcasts: the live feed's searches (taxonomy label + fixed phrase, day-keyed shared
cache, the feed cap and the global caps), ≤ 6 topics × 2 formats. Every article is checked
locally until 6 per topic pass (safe_fetch + extraction, ≥ 400 words; no LLM, no Firestore
write); a failing one is dropped, so a judge never hits a dead link. Production write: 3
`persona_feeds/{p}` docs (public outlet items and search results only, no user data). No LLM.
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
from app.recs import feed_rank as fr
from app.recs.feed import (
    PERSONA_COUNTRY,
    PERSONA_TOPICS,
    FeedSearch,
    Snapshot,
    SnapshotRepo,
    feed_key,
    feed_query,
    offered,
    outlet_candidates,
    side_for,
    thin_topics,
)
from app.recs.models import Format, WebResult
from app.recs.web_search import get_web_search
from app.store.docstore import get_doc_store
from app.store.outlet_repo import OutletStore
from app.store.spend_repo import today_utc

MIN_WORDS = 400
ARTICLES_PER_TOPIC = 6  # checked articles kept per topic (ranking shows 3)
PATTERN = ("local", "global", "local")  # repeated: 60/40 over the kept articles


async def article_ok(fetcher: SafeFetcher, url: str) -> bool:
    try:
        page = await fetcher.fetch(url)
    except FetchError:
        return False
    html = page.body.decode(page.encoding, errors="replace") if page.encoding else page.body
    extracted = await asyncio.to_thread(extract, html, page.url)
    return sum(len(p.split()) for p in extracted.paragraphs) >= MIN_WORDS


def mixed(candidates: list[fr.FeedCandidate]) -> list[WebResult]:
    """Newest first per side, taken in PATTERN order; a side that runs out yields to the other."""
    side = side_for(PERSONA_COUNTRY)
    newest = sorted(candidates, key=lambda c: c.result.published_at or "", reverse=True)
    queues = {s: [c.result for c in newest if side(c) == s] for s in ("local", "global")}
    out: list[WebResult] = []
    i = 0
    while queues["local"] or queues["global"]:
        want = PATTERN[i % len(PATTERN)]
        take = want if queues[want] else ("global" if want == "local" else "local")
        out.append(queues[take].pop(0))
        i += 1
    return list({r.url: r for r in out}.values())


def offered_recordings(results: list[WebResult]) -> list[WebResult]:
    """Cached videos and podcasts were filtered when they were searched; a cache entry made
    before a filter change (decision 64's title check) is checked again here."""
    return [r for r in results if fr.is_feed_page(r)]


async def build(persona: str, graph: ConceptGraph, search: FeedSearch, fetcher: SafeFetcher):
    topics = PERSONA_TOPICS[persona]
    now = datetime.now(UTC)
    lists = await OutletStore(get_doc_store()).read(list(topics))
    by_topic = outlet_candidates(lists, PERSONA_COUNTRY, graph, now)
    thin = thin_topics(by_topic, list(topics))
    gathered = await search.gather(list(topics), graph, now, wait_s=60.0, article_topics=thin)
    web = get_web_search()
    items: list[tuple[str, WebResult]] = []
    dropped = 0
    for topic in topics:
        fallback = [c for c in offered(gathered.by_stem.get(f"feedx:{topic}", []),
                                       PERSONA_COUNTRY)]  # fmt: skip
        kept = 0
        for r in mixed([*by_topic.get(topic, []), *fallback]):
            if kept >= ARTICLES_PER_TOPIC:
                break
            if not await article_ok(fetcher, r.url):
                dropped += 1
                continue
            kept += 1
            items.append((topic, r))
        fmts: tuple[Format, ...] = ("video", "podcast")
        for fmt in fmts:
            entry = await web.cached_entry(
                feed_key(topic, today_utc()), fmt, feed_query(topic, fmt)
            )
            items += [(topic, r) for r in offered_recordings(entry.results if entry else [])]
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
    for persona in args.persona or PERSONA_TOPICS:
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
    parser.add_argument("--persona", action="append", choices=list(PERSONA_TOPICS),
                        help="only these personas (repeatable); default all three")  # fmt: skip
    sys.exit(asyncio.run(main(parser.parse_args())))
