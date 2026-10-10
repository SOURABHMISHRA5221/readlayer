"""Freeze the M2.2 linker precision cases from the M2.1 graph, before any model run (decision 26).

    cd apps/api && uv run python -m evals.freeze_link_cases

Writes, deterministically (seed 7, no LLM or embedding calls):
- evals/cases/link_variants.yaml: 150 exact-alias mentions whose wording differs from the
  concept label (the M2 "variant" precision sample). Mentions that only matched through an alias
  that the M2.2 overrides remove (`remove_alias`) are excluded: their "truth" is a known mislink.
- evals/cases/link_merge.yaml: 100 link_merge pairs with the M2 decision. 50 accepted (a
  concept's label vs one of its merged multi-word aliases) and 50 rejected (two concepts whose
  label embeddings are ≥ DEDUPE_THRESHOLD apart yet stayed separate, so M2 dedupe said "not
  the same"). Held-out docs are never used.
"""

import asyncio
import random
import re
from pathlib import Path

import numpy as np
import yaml

from app.config import get_settings
from app.graph.build import normalize_label
from app.graph.graph import ConceptGraph
from app.graph.models import ConceptGraphFile
from app.graph.overrides import Overrides
from app.ingest.models import USER_INGESTED
from scripts.build_concepts import (
    CONCEPTS_FILE,
    OVERRIDES_FILE,
    heldout_urls,
    load_docs,
    variant_matches,
)

SEED = 7
VARIANTS = 150
MERGES_PER_SIDE = 50
CASES = Path(__file__).parent / "cases"
_ACRONYM = re.compile(r"^[A-Z0-9&.\-]{2,8}$")


def removed_alias_keys(overrides: Overrides) -> set[str]:
    return {normalize_label(a) for r in overrides.remove_alias for a in r.aliases}


def variant_cases(graph: ConceptGraph, docs: list, removed: set[str]) -> list[dict]:
    rows = []
    for doc, d, target in variant_matches(graph, docs):
        if normalize_label(d.label) in removed or normalize_label(d.anchor.exact) in removed:
            continue
        rows.append(
            {
                "content_id": doc.content_id,
                "demand_id": d.id,
                "label": d.label,
                "exact": d.anchor.exact,
                "target": target,
            }
        )
    rows.sort(key=lambda r: (r["content_id"], r["demand_id"]))
    return random.Random(SEED).sample(rows, min(VARIANTS, len(rows)))


def merge_cases(graph: ConceptGraph, threshold: float) -> list[dict]:
    rng = random.Random(SEED)
    accepted = [
        {"a": c.label, "b": alias, "same": True}
        for c in graph.concepts
        for alias in c.aliases
        if " " in alias.strip()
        and not _ACRONYM.match(alias)
        and normalize_label(alias) != normalize_label(c.label)
    ]
    accepted.sort(key=lambda r: (r["a"], r["b"]))
    concepts = graph.concepts
    matrix = np.asarray([graph.vector(c.id) for c in concepts])
    sims = matrix @ matrix.T
    np.fill_diagonal(sims, -1.0)
    rejected = [
        {"a": concepts[i].label, "b": concepts[j].label, "same": False}
        for i, j in zip(*np.nonzero(np.triu(sims) >= threshold), strict=True)
    ]
    rejected.sort(key=lambda r: (r["a"], r["b"]))
    return rng.sample(accepted, min(MERGES_PER_SIDE, len(accepted))) + rng.sample(
        rejected, min(MERGES_PER_SIDE, len(rejected))
    )


def dump(path: Path, header: str, rows: list[dict]) -> None:
    body = yaml.safe_dump(rows, sort_keys=False, allow_unicode=True, width=100)
    path.write_text(header + body, encoding="utf-8")
    print(f"wrote {len(rows)} cases to {path}")


async def main() -> None:
    graph = ConceptGraph(ConceptGraphFile.model_validate_json(CONCEPTS_FILE.read_bytes()))
    print(f"graph {graph.version}, {len(graph)} concepts")
    overrides = Overrides.load(OVERRIDES_FILE)
    held = heldout_urls()
    docs = [d for d in await load_docs() if d.source != USER_INGESTED and d.url not in held]
    variants = variant_cases(graph, docs, removed_alias_keys(overrides))
    dump(
        CASES / "link_variants.yaml",
        "# M2 variant precision sample, frozen from the M2.1 graph before any M2.2 model run\n"
        "# (evals/freeze_link_cases.py, seed 7). Never edited afterwards (decision 26).\n",
        variants,
    )
    merges = merge_cases(graph, get_settings().dedupe_threshold)
    dump(
        CASES / "link_merge.yaml",
        "# link_merge pairs with the M2 decision, frozen from the M2.1 graph before any M2.2\n"
        "# model run (evals/freeze_link_cases.py, seed 7). Never edited afterwards.\n",
        merges,
    )


if __name__ == "__main__":
    asyncio.run(main())
