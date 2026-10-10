"""Store the 15 new held-out articles from their frozen demand set (M2.2 plan §E.2, step 7).

    cd apps/api && uv run python -m scripts.store_heldout

Production write, approved by Sourabh with the M2.2 ship steps. For each doc in
data/heldout_new_demands.json (sha256 checked, per-doc paragraph sha256 checked against the
gitignored build cache): rebuild the content doc exactly as phase 2 would (structure features,
the frozen demands, linked against the current graph file with the current linker), with source
`fetch` like the existing held-out docs, and write it to `contents/`. No re-extraction, no growth.
Skips docs already stored.
"""

import asyncio
import json
import sys
from datetime import UTC, datetime

from app.config import get_settings
from app.graph import enrich
from app.graph.graph import ConceptGraph
from app.graph.linking import link_demands
from app.graph.models import ConceptGraphFile
from app.ingest.extract import build_paragraphs
from app.ingest.features import parse_structure, structure
from app.ingest.models import ContentDoc, Demand, StoredParagraph
from app.log import configure_logging
from app.store.blob_repo import read_bytes
from app.store.content_repo import get_content_store
from scripts.build_cache import BuildCache
from scripts.build_concepts import CACHE_DIR, GCS_URI
from scripts.freeze_heldout_demands import TEXT_DIR, paragraphs_sha
from scripts.heldout_headline import LINK_THRESHOLD, _verify_freeze


async def main() -> int:
    configure_logging("WARNING")
    graph = ConceptGraph(ConceptGraphFile.model_validate_json(await read_bytes(GCS_URI)))
    cache = BuildCache(CACHE_DIR, get_settings())
    ledger: list = []
    store = get_content_store()

    async def embed(texts):
        return await cache.embed(texts, "SEMANTIC_SIMILARITY")

    async def confirm(questions):
        return await enrich.confirm_links(questions, cache.run, ledger)

    stored = skipped = 0
    for frozen in _verify_freeze()["docs"]:
        cid = frozen["content_id"]
        if await store.get(cid) is not None:
            skipped += 1
            continue
        cached = json.loads((TEXT_DIR / f"{cid}.json").read_text(encoding="utf-8"))
        texts = [p["text"] for p in cached["paragraphs"]]
        if paragraphs_sha(texts) != frozen["paragraphs_sha256"]:
            raise SystemExit(f"cached paragraphs changed for {frozen['url']}")
        paragraphs = build_paragraphs(texts)
        assert [p.id for p in paragraphs] == frozen["paragraph_ids"]
        demands = [Demand.model_validate(d) for d in frozen["demands"]]
        linked, _ = await link_demands(
            graph, demands, {p.id: p.text for p in paragraphs}, LINK_THRESHOLD,
            embed=embed, confirm=confirm, site=cached.get("site") or "",
            url=cached.get("final_url") or frozen["url"],
        )  # fmt: skip
        dense = frozen.get("dense", {})
        doc = ContentDoc(
            content_id=cid,
            url=frozen["url"],
            final_url=cached.get("final_url") or frozen["url"],
            title=(cached.get("title") or frozen["url"])[:300],
            site=(cached.get("site") or "")[:120],
            source="fetch",
            fetched_at=datetime.now(UTC).isoformat(),
            paragraphs=[
                StoredParagraph(
                    id=p.id,
                    text=p.text,
                    structure=structure(parse_structure(p.text), dense.get(p.id, False)),
                )
                for p in paragraphs
            ],  # fmt: skip
            demands=linked,
            demands_dropped=0,
            llm_calls=[],
        )
        await store.put(doc)
        stored += 1
        print(f"stored {cid[:8]} {frozen['domain']:12s} {len(linked)} demands, "
              f"{sum(d.target_id is not None for d in linked)} linked")  # fmt: skip
    print(f"stored {stored}, already there {skipped}; new spend ${cache.llm_cost_new:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
