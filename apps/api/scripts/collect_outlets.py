"""Decision 50: run the outlet collection locally. No LLM, no search API, no reader data.

    cd apps/api && uv run python -m scripts.collect_outlets --dry-run   # counts only, no write
    cd apps/api && uv run python -m scripts.collect_outlets             # write rec_cache/outlets:*

The dry run fetches and parses every registry feed and prints, per topic and outlet, how many
fresh article items this run would merge; it writes nothing. Without --dry-run it merges them
into the configured Firestore (≤ 14 `rec_cache/outlets:<topic>` docs; the emulator in the
harness). Production runs go through Cloud Scheduler → POST /v1/internal/feeds/collect.
"""

import argparse
import asyncio
import sys
from datetime import UTC, datetime

from app.config import get_settings
from app.graph.taxonomy import DOMAIN_IDS
from app.ingest.safe_fetch import SafeFetcher
from app.log import configure_logging
from app.recs.outlet_job import CollectReport, collect, fetch_feeds, topic_items
from app.recs.outlets import feed_urls
from app.store.docstore import get_doc_store
from app.store.outlet_repo import OutletStore


async def main(args: argparse.Namespace) -> int:
    configure_logging("WARNING")
    now = datetime.now(UTC)
    if args.dry_run:
        report = CollectReport()
        parsed = await fetch_feeds(SafeFetcher(), feed_urls(), report)
        for topic in DOMAIN_IDS:
            counts = {o: len(i) for o, i in topic_items(topic, parsed, now).items()}
            print(f"{topic:12} {sum(counts.values()):4}  {counts}")
        print(f"\nfeeds answered {report.feeds_ok}, failed {len(report.feeds_failed)}")
        for f in report.feeds_failed:
            print(f"  failed: {f}")
        print("dry run: nothing written")
        return 0
    settings = get_settings()
    target = settings.firestore_emulator_host or settings.db_project
    print(f"writing rec_cache/outlets:* to {target}")
    report = await collect(SafeFetcher(), OutletStore(get_doc_store()), now)
    for topic, counts in report.stored.items():
        print(f"{topic:12} stored {counts}  (new this run {report.fresh[topic]})")
    print(f"\nfeeds answered {report.feeds_ok}, failed {len(report.feeds_failed)}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    sys.exit(asyncio.run(main(parser.parse_args())))
