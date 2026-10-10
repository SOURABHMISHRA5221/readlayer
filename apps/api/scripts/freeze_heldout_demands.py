"""Freeze the demand set for the M2.2 held-out articles (plan run order step 2, decision 26).

    cd apps/api && uv run python -m scripts.freeze_heldout_demands [--old-counts]

New 15 (held-out lines 16–30): fetch through safe_fetch, extract, build paragraphs and run
`extract_demands` (current prompt) ONCE. Writes:
- data/build_cache/heldout/<content_id>.json (gitignored): title, site, url, paragraphs; the
  publisher's text never lands in the repo;
- data/heldout_new_demands.json (committed): per doc the paragraph ids, a sha256 of the
  paragraphs, and the demands (ids, labels, types, anchors, salience); plus
  data/heldout_new_demands.sha256 with the file's sha256.
Every headline run links this same set; storing the docs later checks both hashes first.
Refuses to overwrite an existing freeze.

--old-counts: re-extracts the first 15 (stored docs, read-only) with the current prompt, locally,
and prints per-doc demand counts next to the stored v1 counts (decision 26 for a prompt bump).
Nothing is written to Firestore by either mode.
"""

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path

from app import llm
from app.ingest.demands import extract_demands
from app.ingest.extract import build_paragraphs, extract
from app.ingest.safe_fetch import SafeFetcher
from app.ingest.urls import url_hash
from app.log import configure_logging
from app.store.content_repo import get_content_store
from scripts.build_concepts import CACHE_DIR, DATA_DIR
from scripts.eval_heldout import HELDOUT_TARGET, read_heldout

FREEZE_FILE = DATA_DIR / "heldout_new_demands.json"
SHA_FILE = DATA_DIR / "heldout_new_demands.sha256"
TEXT_DIR = CACHE_DIR / "heldout"
SPEND_LIMIT_USD = 6.0  # refuse to start above this (daily cap is 8)


def paragraphs_sha(texts: list[str]) -> str:
    return hashlib.sha256("\n\n".join(texts).encode()).hexdigest()


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def freeze_new() -> None:
    if FREEZE_FILE.exists():
        raise SystemExit(f"{FREEZE_FILE} exists: the demand set is frozen")
    entries = read_heldout()[HELDOUT_TARGET:]
    fetcher = SafeFetcher()
    TEXT_DIR.mkdir(parents=True, exist_ok=True)
    docs, cost = [], 0.0
    for e in entries:
        page = await fetcher.fetch(e.url)
        html = page.body.decode(page.encoding, errors="replace") if page.encoding else page.body
        ex = await asyncio.to_thread(extract, html, page.url)
        paragraphs = build_paragraphs(ex.paragraphs)
        texts = [p.text for p in paragraphs]
        result = await extract_demands(paragraphs)
        cost += sum(c.cost_usd for c in result.calls)
        cid = url_hash(e.url)
        (TEXT_DIR / f"{cid}.json").write_text(
            json.dumps(
                {
                    "url": e.url,
                    "final_url": page.url,
                    "title": ex.title or ex.site or page.url,
                    "site": ex.site,
                    "paragraphs": [{"id": p.id, "text": p.text} for p in paragraphs],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        docs.append(
            {
                "content_id": cid,
                "url": e.url,
                "domain": e.domain,
                "paragraph_ids": [p.id for p in paragraphs],
                "paragraphs_sha256": paragraphs_sha(texts),
                "prompt_version": result.calls[0].prompt_version if result.calls else None,
                "dense": result.dense,
                "demands": [d.model_dump() for d in result.demands],
            }
        )
        n_p, n_d = len(paragraphs), len(result.demands)
        print(f"{e.domain:12s} {n_p:3d} paragraphs {n_d:3d} demands  {e.url}")
    FREEZE_FILE.write_text(json.dumps({"docs": docs}, indent=1, ensure_ascii=False) + "\n")
    SHA_FILE.write_text(f"{file_sha(FREEZE_FILE)}  {FREEZE_FILE.name}\n")
    print(f"froze {len(docs)} docs, cost ${cost:.4f}; sha256 {file_sha(FREEZE_FILE)}")


async def old_counts() -> None:
    content = get_content_store()
    cost = 0.0
    print("| content_id | domain | stored (v1) | current prompt | concept/term v1 → now |")
    print("|---|---|---|---|---|")
    for e in read_heldout()[:HELDOUT_TARGET]:
        doc = await content.get(url_hash(e.url))
        if doc is None:
            print(f"| {url_hash(e.url)[:8]} | {e.domain} | missing | | |")
            continue
        paragraphs = build_paragraphs([p.text for p in doc.paragraphs])
        result = await extract_demands(paragraphs)
        cost += sum(c.cost_usd for c in result.calls)

        def ct(ds) -> int:
            return sum(d.type in ("concept", "term") for d in ds)

        print(
            f"| {doc.content_id[:8]} | {e.domain} | {len(doc.demands)} | {len(result.demands)} "
            f"| {ct(doc.demands)} → {ct(result.demands)} |"
        )
    print(f"cost ${cost:.4f}")


async def main(args: argparse.Namespace) -> int:
    configure_logging("WARNING")
    spent = await llm.get_spend_store().get_today()
    print(f"today's LLM spend before: ${spent:.4f}")
    if spent > SPEND_LIMIT_USD:
        print(f"refusing: above ${SPEND_LIMIT_USD:.2f}")
        return 2
    await (old_counts() if args.old_counts else freeze_new())
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--old-counts", action="store_true")
    sys.exit(asyncio.run(main(parser.parse_args())))
