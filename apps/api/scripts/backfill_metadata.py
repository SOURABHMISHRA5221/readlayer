"""Backfill publisher metadata (description, author, published, image) on ingested docs.

Run:  cd apps/api && uv run python -m scripts.backfill_metadata [--dry-run] [--force]

Fetches each doc's final URL through safe_fetch (same SSRF, robots and size rules as ingestion)
and reads metadata only: no LLM call, no change to paragraphs or demands. Docs that already have
any metadata field are skipped unless --force. Failures are logged and left untouched.
"""

import argparse
import asyncio
import logging
from collections import Counter
from dataclasses import dataclass

from app.ingest import safe_fetch as fetch
from app.ingest.extract import Metadata, extract_metadata
from app.ingest.models import ContentDoc
from app.log import configure_logging
from app.store.content_repo import ContentStore, get_content_store

log = logging.getLogger("scripts.backfill_metadata")

CONCURRENCY = 4


@dataclass(frozen=True)
class Result:
    content_id: str
    status: str  # "updated" | "empty" | "failed" | "skipped"
    code: str | None = None


def needs_backfill(doc: ContentDoc, force: bool) -> bool:
    return force or not (doc.description or doc.author or doc.published or doc.image)


def with_metadata(doc: ContentDoc, meta: Metadata) -> ContentDoc:
    return doc.model_copy(
        update={
            "description": meta.description,
            "author": meta.author,
            "published": meta.published,
            "image": meta.image,
        }
    )


async def backfill_one(
    doc: ContentDoc, store: ContentStore, *, dry_run: bool, force: bool
) -> Result:
    if not needs_backfill(doc, force):
        return Result(doc.content_id, "skipped")
    try:
        page = await fetch.safe_fetch(doc.final_url or doc.url)
    except fetch.FetchError as exc:
        return Result(doc.content_id, "failed", exc.code)
    html = page.body.decode(page.encoding, errors="replace") if page.encoding else page.body
    meta = await asyncio.to_thread(extract_metadata, html, page.url)
    if meta == Metadata():
        return Result(doc.content_id, "empty")
    if not dry_run:
        await store.put(with_metadata(doc, meta))
    return Result(doc.content_id, "updated")


async def run(*, dry_run: bool, force: bool) -> Counter[str]:
    store = get_content_store()
    docs = [d async for d in store.iter_all()]
    gate = asyncio.Semaphore(CONCURRENCY)

    async def guarded(doc: ContentDoc) -> Result:
        async with gate:
            return await backfill_one(doc, store, dry_run=dry_run, force=force)

    results = await asyncio.gather(*(guarded(d) for d in docs))
    for r in results:
        if r.status == "failed":
            log.warning("metadata fetch failed", extra={"content_id": r.content_id, "code": r.code})
    return Counter(r.status for r in results)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="fetch and report, write nothing")
    parser.add_argument("--force", action="store_true", help="refetch docs that have metadata")
    args = parser.parse_args()
    configure_logging()
    counts = asyncio.run(run(dry_run=args.dry_run, force=args.force))
    log.info("metadata backfill done", extra={"counts": dict(counts), "dry_run": args.dry_run})


if __name__ == "__main__":
    main()
