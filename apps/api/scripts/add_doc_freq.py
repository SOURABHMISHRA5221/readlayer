"""Add `doc_freq` to the current concept graph without a rebuild (DESIGN §2, §15.2).

doc_freq = distinct near-duplicate doc groups among corpus docs with a demand linked to the
concept (syndicated copies count once; held-out and reader-ingested docs never count). The
build writes it from now on; this patches the graph built before the field existed. Grouping
reuses the build's cached title+lead embeddings, so a rerun costs nothing.

Run:  cd apps/api && uv run python -m scripts.add_doc_freq [--upload]

--upload refuses unless the local concepts.json is byte-identical to the one in GCS (other than
doc_freq), so it can't overwrite a newer graph with a stale local copy.
"""

import argparse
import asyncio
import sys
from collections.abc import Iterable, Mapping

from app.config import get_settings
from app.graph.models import ConceptGraphFile
from app.ingest.models import ContentDoc
from app.log import configure_logging
from app.store.blob_repo import read_bytes, write_bytes
from scripts.build_cache import BuildCache
from scripts.build_concepts import (
    CACHE_DIR,
    CONCEPTS_FILE,
    GCS_URI,
    corpus_sources,
    find_duplicates,
    load_docs,
    select_corpus,
)


def doc_freq(docs: Iterable[ContentDoc], group_of: Mapping[str, int]) -> dict[str, int]:
    groups: dict[str, set[int]] = {}
    for doc in docs:
        group = group_of[doc.content_id]
        for d in doc.demands:
            if d.target_id:
                groups.setdefault(d.target_id, set()).add(group)
    return {cid: len(g) for cid, g in groups.items()}


def with_doc_freq(file: ConceptGraphFile, freq: Mapping[str, int]) -> ConceptGraphFile:
    return file.model_copy(
        update={
            "concepts": [
                c.model_copy(update={"doc_freq": freq.get(c.id, 0)}) for c in file.concepts
            ]
        }  # fmt: skip
    )


async def main(args: argparse.Namespace) -> int:
    configure_logging("WARNING")
    cache = BuildCache(CACHE_DIR, get_settings())
    local = ConceptGraphFile.model_validate_json(CONCEPTS_FILE.read_bytes())
    if args.upload:
        remote = ConceptGraphFile.model_validate_json(await read_bytes(GCS_URI))
        strip = {"concepts": {"__all__": {"doc_freq"}}}
        if remote.model_dump(exclude=strip) != local.model_dump(exclude=strip):
            print(f"local {CONCEPTS_FILE} differs from {GCS_URI}; not uploading")
            return 1
    docs = await load_docs()
    corpus = select_corpus(docs, corpus_sources())
    dup = await find_duplicates(corpus, cache)
    group_of = {corpus[i].content_id: g for g, members in enumerate(dup.groups) for i in members}
    freq = doc_freq(corpus, group_of)
    patched = with_doc_freq(local, freq)
    CONCEPTS_FILE.write_text(patched.model_dump_json(), encoding="utf-8")

    counted = sum(1 for c in patched.concepts if c.doc_freq)
    print(f"{len(corpus)} corpus docs in {len(dup.groups)} groups")
    print(f"doc_freq set on {counted}/{len(patched.concepts)} concepts")
    for c in sorted(patched.concepts, key=lambda c: -c.doc_freq)[:10]:
        print(f"  {c.doc_freq:4d}  {c.label} ({c.domain})")
    print(f"embedding cost this run: ${cache.embed_cost_new:.4f}")
    if args.upload:
        await write_bytes(GCS_URI, CONCEPTS_FILE.read_bytes())
        print(f"uploaded {GCS_URI} (version {patched.version} unchanged)")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--upload", action="store_true", help=f"upload to {GCS_URI}")
    sys.exit(asyncio.run(main(parser.parse_args())))
