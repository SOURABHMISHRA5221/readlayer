"""M9 part 2, R7–R8: where to cut cross-domain prerequisites, from the real model's confidences.

    uv run python -m scripts.replay_prereqs propose    # model call; writes evals/local/ only
    uv run python -m scripts.replay_prereqs report     # after the blind verdicts are committed

`propose`: for every concept grown live up to the cutoff, its prerequisite pool as growth builds it
now (`prereq_pool` on the served graph, minus the concept itself), one batched `concept_prereqs`
(MODEL_FAST, through llm.py). Writes `evals/local/prereq_proposals.json` (with confidences) and
`evals/local/prereq_blind.json` (cross-domain edges only, no confidences) for judging. Nothing else
but the spend ledger. `report`: joins `evals/prereq_verdicts.json` (judged blind, committed first)
to the confidences and writes `evals/prereq_replay.md` with the chosen `CROSS_DOMAIN_MIN`.
"""

import asyncio
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

EVALS = Path(__file__).resolve().parents[1] / "evals"
LOCAL = EVALS / "local"
CUTOFF = datetime(2026, 10, 14, 9, 24, 55, 300_000, tzinfo=UTC)
KEEP_RIGHT = 0.90  # of the right cross-domain edges (R8)


def pool_without(pool: list, concept_id: str) -> list:
    """The concept is in the served graph now, so its own pool would offer it (R7)."""
    return [c for c in pool if c.id != concept_id]


@dataclass(frozen=True)
class Edge:
    concept: str
    prereq: str
    confidence: float
    right: bool


def choose(edges: list[Edge]) -> tuple[float, dict[str, int]]:
    """The lowest threshold that drops every wrong edge while keeping ≥ 90% of the right ones;
    if none does both, the highest that still keeps ≥ 90% of the right ones (R8)."""
    right = [e for e in edges if e.right]
    wrong = [e for e in edges if not e.right]
    cuts = sorted({0.0, *(e.confidence for e in edges)})

    def kept_right(t: float) -> float:
        return sum(e.confidence >= t for e in right) / len(right) if right else 1.0

    ok = [t for t in cuts if kept_right(t) >= KEEP_RIGHT]
    clean = [t for t in ok if all(e.confidence < t for e in wrong)]
    threshold = min(clean) if clean else max(ok)
    counts = {
        "right": len(right),
        "wrong": len(wrong),
        "dropped_right": sum(e.confidence < threshold for e in right),
        "dropped_wrong": sum(e.confidence < threshold for e in wrong),
        "kept_wrong": sum(e.confidence >= threshold for e in wrong),
    }
    return threshold, counts


async def propose() -> int:
    from app import llm
    from app.config import get_settings
    from app.graph import enrich
    from app.graph.growth import prereq_pool
    from app.graph.loader import get_graph, load_serving_graph
    from app.store.growth_repo import get_growth_repo

    await load_serving_graph(get_settings().concepts_uri)
    graph = get_graph()
    rows = [r for r in await get_growth_repo().since(None) if r.added_at and r.added_at <= CUTOFF]
    concepts = sorted((r.concept for r in rows), key=lambda c: c.id)
    requests = [
        enrich.PrereqRequest(
            enrich.Entry(c.label, definition=c.definition),
            tuple(
                (x.id, x.label)
                for x in pool_without(prereq_pool(graph, c.embedding, c.domain), c.id)
            ),
        )
        for c in concepts
    ]
    ledger: list[llm.CallMeta] = []
    picks = await enrich.propose_prereqs(requests, llm.run_with_meta, ledger)
    proposals, blind = [], []
    for k, c in enumerate(concepts):
        for p in picks.get(k, []):
            pre = graph.get(p.id)
            if pre is None or p.id == c.id:
                continue
            row = {
                "concept_id": c.id, "concept": c.label, "domain": c.domain,
                "prereq_id": pre.id, "prereq": pre.label, "prereq_domain": pre.domain,
            }  # fmt: skip
            proposals.append(row | {"confidence": p.confidence})
            if pre.domain != c.domain:
                blind.append(row)
    LOCAL.mkdir(exist_ok=True)
    cost = sum(m.cost_usd for m in ledger)
    (LOCAL / "prereq_proposals.json").write_text(
        json.dumps({"cost_usd": cost, "concepts": len(concepts), "edges": proposals}, indent=1)
    )
    (LOCAL / "prereq_blind.json").write_text(json.dumps(blind, indent=1, ensure_ascii=False))
    print(
        f"{len(concepts)} concepts, {len(proposals)} edges ({len(blind)} cross-domain), ${cost:.4f}"
    )
    return 0


def report() -> int:
    proposals = json.loads((LOCAL / "prereq_proposals.json").read_text())
    verdicts = {
        (v["concept_id"], v["prereq_id"]): v["verdict"] == "right"
        for v in json.loads((EVALS / "prereq_verdicts.json").read_text())["edges"]
    }
    cross = [e for e in proposals["edges"] if e["domain"] != e["prereq_domain"]]
    edges = [
        Edge(
            e["concept"], e["prereq"], e["confidence"], verdicts[(e["concept_id"], e["prereq_id"])]
        )
        for e in cross
    ]
    threshold, n = choose(edges)
    lines = [
        "# Cross-domain prerequisite replay (M9 part 2, R7–R8)",
        "",
        f"{proposals['concepts']} concepts grown live up to {CUTOFF.isoformat()}; pools as "
        "growth builds them now, minus the concept; one batched `concept_prereqs` on "
        f"MODEL_FAST, ${proposals['cost_usd']:.4f}. {len(proposals['edges'])} edges, "
        f"{len(cross)} cross-domain.",
        "Every cross-domain edge was judged right or wrong with the confidences hidden (borderline "
        "counts as wrong) and the verdicts committed (`prereq_verdicts.json`) before this join.",
        "",
        f"**CROSS_DOMAIN_MIN = {threshold}**: of {n['right']} right cross-domain edges "
        f"{n['dropped_right']} dropped; of {n['wrong']} wrong, {n['dropped_wrong']} dropped and "
        f"{n['kept_wrong']} kept. Chosen and measured on the same set (in-sample).",
        "",
        "| concept | prerequisite | confidence | verdict | kept |",
        "|---|---|---|---|---|",
    ]
    for e in sorted(edges, key=lambda e: (-e.confidence, e.concept)):
        verdict = "right" if e.right else "wrong"
        kept = "yes" if e.confidence >= threshold else "no"
        lines.append(f"| {e.concept} | {e.prereq} | {e.confidence:.2f} | {verdict} | {kept} |")
    (EVALS / "prereq_replay.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(lines[6])
    return 0


if __name__ == "__main__":
    step = sys.argv[1] if len(sys.argv) > 1 else ""
    if step == "propose":
        sys.exit(asyncio.run(propose()))
    if step == "report":
        sys.exit(report())
    sys.exit("usage: replay_prereqs propose | report")
