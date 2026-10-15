"""Decision 50 §A: is every registry outlet readable in Gloss? Local, read-only, no LLM.

    cd apps/api && uv run python -m scripts.check_outlets            # print the report
    cd apps/api && uv run python -m scripts.check_outlets --write    # + docs/evidence/d50/

Every section feed is fetched and parsed (items per feed); then, per outlet, its 3 newest
article items (across its feeds, one per URL) are fetched and extracted exactly as "Open here"
would (safe_fetch + trafilatura). An outlet is `readable` when ≥ 2 of 3 reach 400 words;
unreadable outlets are dropped from the launch set by hand.
"""

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

from app.ingest.extract import extract
from app.ingest.safe_fetch import FetchError, SafeFetcher
from app.recs.outlet_feed import outlet_items
from app.recs.outlet_job import CollectReport, fetch_feeds
from app.recs.outlets import REGISTRY, Outlet, feed_urls

OUT = Path(__file__).resolve().parents[3] / "docs" / "evidence" / "d50" / "outlets.txt"
SAMPLE = 3
MIN_WORDS = 400
READABLE_AT = 2


async def words(fetcher: SafeFetcher, url: str) -> int | str:
    try:
        page = await fetcher.fetch(url)
    except FetchError as exc:
        return exc.code
    html = page.body.decode(page.encoding, errors="replace") if page.encoding else page.body
    extracted = await asyncio.to_thread(extract, html, page.url)
    return sum(len(p.split()) for p in extracted.paragraphs)


async def check_outlet(fetcher: SafeFetcher, outlet: Outlet, parsed, now) -> list[str]:
    items = [r for topic, us in outlet.sections.items()
             for r in outlet_items(outlet, (e for u in us if u in parsed for e in parsed[u]), now,
                                   topic)]  # fmt: skip
    newest = sorted({r.url: r for r in items}.values(), key=lambda r: r.published_at or "",
                    reverse=True)[:SAMPLE]  # fmt: skip
    counts = [await words(fetcher, r.url) for r in newest]
    ok = sum(isinstance(c, int) and c >= MIN_WORDS for c in counts)
    verdict = "readable" if ok >= READABLE_AT else "UNREADABLE"
    lines = [f"{outlet.name} ({outlet.id}, {outlet.region}): {verdict}, {ok}/{len(counts)} "
             f"articles ≥ {MIN_WORDS} words"]  # fmt: skip
    lines += [f"    {c!s:>6}  {r.url}" for c, r in zip(counts, newest, strict=True)]
    return lines


async def main(args: argparse.Namespace) -> int:
    now = datetime.now(UTC)
    fetcher = SafeFetcher()
    report = CollectReport()
    parsed = await fetch_feeds(fetcher, feed_urls(), report)
    stamp = now.isoformat(timespec="minutes")
    lines = [
        f"# Decision 50 outlet check, {stamp} (scripts/check_outlets.py; no LLM)",
        "",
        f"Feeds: {report.feeds_ok} answered, {len(report.feeds_failed)} failed",
        "",
    ]
    for url in feed_urls():
        lines.append(f"  {len(parsed[url]) if url in parsed else 'FAIL':>4}  {url}")
    lines += [f"  failed: {f}" for f in report.feeds_failed]
    lines.append("")
    for outlet in REGISTRY:
        lines += await check_outlet(fetcher, outlet, parsed, now)
    text = "\n".join(lines) + "\n"
    print(text)
    if args.write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(text, encoding="utf-8")
        print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="write docs/evidence/d50/outlets.txt")
    sys.exit(asyncio.run(main(parser.parse_args())))
