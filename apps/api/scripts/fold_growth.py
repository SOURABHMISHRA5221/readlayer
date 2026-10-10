"""Fold concepts grown online into concepts.json in Cloud Storage (M2.2 plan §C.5).

    cd apps/api && uv run python -m scripts.fold_growth            # list what would be folded
    cd apps/api && uv run python -m scripts.fold_growth --upload   # back up, then upload

Lists every `graph_growth/` concept not yet in the GCS file (id, label, domain, kind, source
content id): anonymous pastes become permanent graph data here, so the list goes to Sourabh with
the fold's counts first. With --upload: download the current file and upload it unchanged as
concepts.prev.json (the backup) BEFORE writing the new one; merge, assert a DAG, bump the version
and upload. Growth docs stay in place; the API's startup merge skips ids already in the file.
"""

import argparse
import asyncio
import sys
from datetime import UTC, datetime

from app.graph.graph import ConceptGraph
from app.graph.models import ConceptGraphFile
from app.log import configure_logging
from app.store.blob_repo import read_bytes, write_bytes
from app.store.growth_repo import GrownConcept, get_growth_repo
from scripts.build_concepts import GCS_PREV_URI, GCS_URI


def fold(current: ConceptGraphFile, grown: list[GrownConcept]) -> tuple[ConceptGraphFile, list]:
    have = {c.id for c in current.concepts}
    fresh = [g for g in grown if g.concept.id not in have]
    base = current.version.split("+")[0]
    total = len(current.concepts) + len(fresh)
    stamp = datetime.now(UTC).date().isoformat()
    file = ConceptGraphFile(
        version=f"{stamp}-folded-{total}" if fresh else current.version,
        domains=current.domains,
        concepts=[*current.concepts, *(g.concept for g in fresh)],
    )
    if not ConceptGraph(file).is_acyclic():
        raise SystemExit(f"folding {len(fresh)} concepts onto {base} would create a cycle")
    return file, fresh


async def main(args: argparse.Namespace) -> int:
    configure_logging("WARNING")
    return await run(args.upload)


async def run(upload: bool) -> int:
    raw = await read_bytes(GCS_URI)
    current = ConceptGraphFile.model_validate_json(raw)
    grown = await get_growth_repo().since(None)
    file, fresh = fold(current, grown)
    print(f"{GCS_URI}: version {current.version}, {len(current.concepts)} concepts")
    print(f"growth docs: {len(grown)}; new to the file: {len(fresh)}")
    for g in fresh:
        c = g.concept
        print(f"  {c.id} | {c.label} | {c.domain} | {c.kind} | from {g.source_cid}")
    if not upload or not fresh:
        print("nothing uploaded")
        return 0
    await write_bytes(GCS_PREV_URI, raw)  # backup first: the previous file, byte for byte
    await write_bytes(GCS_URI, file.model_dump_json().encode())
    print(f"backed up to {GCS_PREV_URI}; uploaded version {file.version}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--upload", action="store_true")
    sys.exit(asyncio.run(main(parser.parse_args())))
