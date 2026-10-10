"""Preview the corpus re-link and the demo-persona diff for the seeded graph (M2.2 plan §B.4).

    cd apps/api && uv run python -m scripts.relink_dry_run

Reads every stored content doc (Firestore, read-only), re-links its demands IN MEMORY against
data/concepts.seeded.json with the current linker (LINK_THRESHOLD 0.865, site and URL for the
jurisdiction cues), and counts the docs and demands whose links change, with and without the 30
held-out docs. Saves the previewed links to data/build_cache/relink_preview.json together with
the seeded graph's sha256, so the later write applies exactly what was approved (and refuses if
the graph changed). Then, for each demo article × persona, compares the deterministic annotate
output (no LLM) on the old graph and stored links vs the seeded graph and previewed links.

Appends a "Production writes" section to evals/seed_report.md. Writes nothing to Firestore.
"""

import asyncio
import hashlib
import json
import sys
from datetime import UTC, datetime
from typing import Any

from app import llm
from app.config import get_settings
from app.graph import enrich
from app.graph.graph import ConceptGraph
from app.graph.linking import link_demands
from app.graph.models import ConceptGraphFile
from app.ingest.models import ContentDoc
from app.ingest.urls import url_hash
from app.log import configure_logging
from app.reader.personas import PERSONAS
from app.scoring import scorer
from app.store.docstore import get_doc_store
from app.store.persona_repo import get_template
from app.store.reader_repo import state_from_demo
from scripts.build_cache import BuildCache
from scripts.build_concepts import CACHE_DIR, CONCEPTS_FILE, load_docs
from scripts.eval_heldout import read_heldout
from scripts.seed_glossaries import REPORT_FILE, SEEDED_FILE
from scripts.warm_demo import DEMO_ARTICLES

LINK_THRESHOLD = 0.865
PREVIEW_FILE = CACHE_DIR / "relink_preview.json"
EXPLAIN_PART_USD = 0.004  # one Background generation + verify, M5/M6 measurements


def _load(path) -> tuple[ConceptGraph, str]:
    raw = path.read_bytes()
    return ConceptGraph(ConceptGraphFile.model_validate_json(raw)), hashlib.sha256(raw).hexdigest()


async def relink(
    docs: list[ContentDoc], graph: ConceptGraph, cache: BuildCache, ledger: list
) -> dict[str, dict[str, str | None]]:
    async def embed(texts: list[str]) -> list[list[float]]:
        return await cache.embed(texts, "SEMANTIC_SIMILARITY")

    async def confirm(questions):
        return await enrich.confirm_links(questions, cache.run, ledger)

    out: dict[str, dict[str, str | None]] = {}
    for doc in docs:
        fresh = [d.model_copy(update={"target_id": None}) for d in doc.demands]
        linked, _ = await link_demands(
            graph,
            fresh,
            {p.id: p.text for p in doc.paragraphs},
            LINK_THRESHOLD,
            embed=embed,
            confirm=confirm,
            site=doc.site,
            url=doc.final_url or doc.url,
        )
        out[doc.content_id] = {d.id: d.target_id for d in linked}
    return out


def changes(docs: list[ContentDoc], preview: dict[str, dict[str, str | None]], held: set[str]):
    rows = {"all": [0, 0], "without held-out": [0, 0]}  # [docs changed, demands changed]
    for doc in docs:
        n = sum(preview[doc.content_id].get(d.id) != d.target_id for d in doc.demands)
        for key in ("all", "without held-out"):
            if key == "without held-out" and doc.content_id in held:
                continue
            rows[key][0] += n > 0
            rows[key][1] += n
    return rows


async def persona_diff(
    docs: dict[str, ContentDoc],
    preview: dict[str, dict[str, str | None]],
    old: ConceptGraph,
    new: ConceptGraph,
) -> list[dict[str, Any]]:
    store = get_doc_store()
    now = datetime.now(UTC)
    rows = []
    for cid in DEMO_ARTICLES:
        doc = docs.get(cid)
        if doc is None:
            continue
        relinked = doc.model_copy(
            update={
                "demands": [
                    d.model_copy(update={"target_id": preview[cid].get(d.id)}) for d in doc.demands
                ]
            }
        )
        for persona in PERSONAS:
            template = await get_template(store, persona)
            state = state_from_demo("dry-run", persona, template, False)
            before = scorer.annotate(doc, old, state, "balanced", now).spans
            after = scorer.annotate(relinked, new, state, "balanced", now).spans
            b = {s.concept_id: s.label for s in before}
            a = {s.concept_id: s.label for s in after}
            rows.append(
                {
                    "article": cid[:8],
                    "persona": persona,
                    "before": len(b),
                    "after": len(a),
                    "added": sorted(a[k] for k in a.keys() - b.keys()),
                    "removed": sorted(b[k] for k in b.keys() - a.keys()),
                }
            )
    return rows


async def main() -> int:
    configure_logging("WARNING")
    old, _ = _load(CONCEPTS_FILE)
    new, sha = _load(SEEDED_FILE)
    cache = BuildCache(CACHE_DIR, get_settings())
    ledger: list[llm.CallMeta] = []
    docs = await load_docs()
    held = {url_hash(e.url) for e in read_heldout()}
    preview = await relink(docs, new, cache, ledger)
    PREVIEW_FILE.write_text(json.dumps({"graph_sha256": sha, "links": preview}), encoding="utf-8")
    counts = changes(docs, preview, held)
    diff = await persona_diff({d.content_id: d for d in docs}, preview, old, new)
    added = sum(len(r["added"]) for r in diff)
    spend = cache.llm_cost_new + cache.embed_cost_new
    lines = [
        "",
        "## Production writes (dry run of the re-link and the demo diff)",
        "",
        f"Seeded graph sha256 {sha[:16]}; {len(docs)} stored content docs re-linked in memory "
        f"(link_confirm on MODEL_QUALITY, {sum(m.fell_back for m in ledger)} fallback batches); "
        f"new spend ${spend:.3f}.",
        "",
        "| scope | docs whose links change | demands whose link changes |",
        "|---|---|---|",
        *[f"| {k} | {v[0]} | {v[1]} |" for k, v in counts.items()],
        "",
        "Demo articles × personas (deterministic annotate, balanced density, no LLM):",
        "",
        "| article | persona | spans before | after | added | removed |",
        "|---|---|---|---|---|---|",
        *[
            f"| {r['article']} | {r['persona']} | {r['before']} | {r['after']} "
            f"| {', '.join(r['added']) or '–'} | {', '.join(r['removed']) or '–'} |"
            for r in diff
        ],
        "",
        f"New demo spans to warm with warm_demo: {added} (≈ ${added * EXPLAIN_PART_USD:.2f}, one "
        "Background each; restatements are shared and mostly cached).",
    ]
    text = REPORT_FILE.read_text(encoding="utf-8").rstrip("\n") + "\n" + "\n".join(lines) + "\n"
    REPORT_FILE.write_text(text, encoding="utf-8")
    print("\n".join(lines))
    print(f"preview saved to {PREVIEW_FILE} (gitignored)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
