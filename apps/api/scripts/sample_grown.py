"""M9 part 2, P3 (R9–R11): a fresh, fixed sample of 30 concepts grown live, for judging.

    uv run python -m scripts.sample_grown --cutoff 2026-10-14T09:24:55.3Z --seed 1015

Read only. Takes every `graph_growth` concept with `added_at` ≤ the cutoff, sorted by id, and a
seeded random 30 of them. Writes `evals/grown_sample.json` (committed: all ids, the seed, and for
the 30 their label, definition, domain, kind and the source page's type) and
`evals/local/grown_sample_sentences.json` (gitignored: the sentence each was grown from, which can
come from a reader's own page).
"""

import argparse
import asyncio
import json
import random
import sys
from datetime import datetime
from pathlib import Path

EVALS = Path(__file__).resolve().parents[1] / "evals"
N = 30


def sample(ids: list[str], seed: int, n: int = N) -> list[str]:
    """Deterministic for the same ids (any order) and seed."""
    return random.Random(seed).sample(sorted(ids), min(n, len(ids)))


async def main(a: argparse.Namespace) -> int:
    from app.graph.linking import sentence_around
    from app.store.content_repo import get_content_store
    from app.store.growth_repo import get_growth_repo

    cutoff = datetime.fromisoformat(a.cutoff.replace("Z", "+00:00"))
    rows = [r for r in await get_growth_repo().since(None) if r.added_at and r.added_at <= cutoff]
    by_id = {r.concept.id: r for r in rows}
    picked = sample(list(by_id), a.seed)
    store = get_content_store()
    items, sentences = [], {}
    for cid in picked:
        r = by_id[cid]
        doc = await store.get(r.source_cid)
        sentence = ""
        if doc is not None:
            paras = {p.id: p.text for p in doc.paragraphs}
            for d in doc.demands:
                if d.target_id == cid:
                    sentence = sentence_around(
                        paras.get(d.paragraph_id, ""), d.anchor.exact, d.anchor.prefix
                    )
                    break
        c = r.concept
        items.append({"id": cid, "label": c.label, "definition": c.definition, "domain": c.domain,
                      "kind": c.kind, "source_type": doc.source if doc else "missing"})  # fmt: skip
        sentences[cid] = sentence
    out = {"cutoff": a.cutoff, "seed": a.seed, "population": sorted(by_id), "sample": items}
    (EVALS / "grown_sample.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    (EVALS / "local").mkdir(exist_ok=True)
    (EVALS / "local" / "grown_sample_sentences.json").write_text(
        json.dumps(sentences, indent=1, ensure_ascii=False)
    )
    print(f"population {len(by_id)}, sampled {len(items)}")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--cutoff", required=True)
    p.add_argument("--seed", type=int, required=True)
    sys.exit(asyncio.run(main(p.parse_args())))
