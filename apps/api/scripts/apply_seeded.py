"""Apply the approved M2.2 seeding: upload the seeded graph, then re-link stored docs.

    cd apps/api && uv run python -m scripts.apply_seeded --upload-graph
    cd apps/api && uv run python -m scripts.apply_seeded --relink [--include-heldout]

Both steps run only after Sourabh's yes on evals/seed_report.md (decision 34), and only on the
exact files the dry runs produced:
- --upload-graph: data/concepts.seeded.json must still have the sha256 recorded in the re-link
  preview. The current GCS file is uploaded unchanged as concepts.prev.json first (the backup),
  then the seeded file replaces concepts.json. Deploy order (plan Ship 2): the API that can parse
  14 domains is deployed BEFORE this runs.
- --relink: writes the previewed links (data/build_cache/relink_preview.json) to every content
  doc whose links change, demands only (target_id; `grown` stays False). Held-out docs are left
  for after the final headline unless --include-heldout. Prints counts; the dry run's counts are
  the approved ones.
"""

import argparse
import asyncio
import hashlib
import json
import sys

from app.ingest.urls import url_hash
from app.log import configure_logging
from app.store.blob_repo import read_bytes, write_bytes
from app.store.content_repo import get_content_store
from scripts.build_concepts import GCS_PREV_URI, GCS_URI, load_docs
from scripts.eval_heldout import read_heldout
from scripts.relink_dry_run import PREVIEW_FILE
from scripts.seed_glossaries import SEEDED_FILE


def _preview() -> dict:
    preview = json.loads(PREVIEW_FILE.read_text(encoding="utf-8"))
    sha = hashlib.sha256(SEEDED_FILE.read_bytes()).hexdigest()
    if preview["graph_sha256"] != sha:
        raise SystemExit("concepts.seeded.json changed since the re-link dry run; rerun it first")
    return preview


async def upload_graph() -> None:
    _preview()
    previous = await read_bytes(GCS_URI)
    await write_bytes(GCS_PREV_URI, previous)  # backup first, byte for byte
    await write_bytes(GCS_URI, SEEDED_FILE.read_bytes())
    print(f"backed up {GCS_URI} to {GCS_PREV_URI}; uploaded {SEEDED_FILE.name}")


async def relink(include_heldout: bool) -> None:
    links = _preview()["links"]
    held = {url_hash(e.url) for e in read_heldout()}
    store = get_content_store()
    changed = skipped = 0
    for doc in await load_docs():
        if doc.content_id in held and not include_heldout:
            continue
        new = links.get(doc.content_id)
        if new is None:
            skipped += 1
            continue
        demands = [
            d.model_copy(update={"target_id": new.get(d.id, d.target_id)}) for d in doc.demands
        ]
        if [d.target_id for d in demands] == [d.target_id for d in doc.demands]:
            continue
        await store.put(doc.model_copy(update={"demands": demands}))
        changed += 1
    print(f"re-linked {changed} docs; {skipped} docs had no preview (ingested after it)")


async def main(args: argparse.Namespace) -> int:
    configure_logging("WARNING")
    if args.upload_graph:
        await upload_graph()
    if args.relink:
        await relink(args.include_heldout)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--upload-graph", action="store_true")
    parser.add_argument("--relink", action="store_true")
    parser.add_argument("--include-heldout", action="store_true")
    sys.exit(asyncio.run(main(parser.parse_args())))
