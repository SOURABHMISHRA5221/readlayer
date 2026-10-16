"""resolve_names (learning goals, profile edits, onboarding terms) at default vs low
`link_confirm` thinking (decision 69 D). From apps/api, with the project's ADC:

    uv run python -m evals.resolve_effort

Inputs: cases/goal_phrases.yaml (20) and the first 30 phrases of cases/onboarding_topics.yaml,
through `resolve_names` against data/concepts.json, fresh model calls (no cache) at each level.
Rule (fixed before the first run): low passes if it agrees with default on >= 90 % of the names
default resolves. Results go to evals/results/resolve-effort-<time>.json.
"""

import asyncio
import json
import os
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from app import config
from app.graph.graph import ConceptGraph
from app.graph.models import ConceptGraphFile
from app.graph.resolve import resolve_names

ROOT = Path(__file__).parent
GRAPH = ROOT.parent.parent.parent / "data" / "concepts.json"
PASS_AGREEMENT = 0.9


def phrases() -> list[list[str]]:
    goals = yaml.safe_load((ROOT / "cases/goal_phrases.yaml").read_text())
    onb = [c["phrase"] for c in yaml.safe_load((ROOT / "cases/onboarding_topics.yaml").read_text())]
    return [goals, onb[:30]]  # resolve_names sends at most 30 names to the model per call


async def run(effort: str | None, graph: ConceptGraph) -> dict[str, Any]:
    os.environ["LLM_REASONING_EFFORT"] = json.dumps({"link_confirm": effort} if effort else {})
    config.get_settings.cache_clear()
    settings = config.get_settings()
    picks: dict[str, str] = {}
    ledger: list = []
    for batch in phrases():
        ids, _ = await resolve_names(graph, batch, settings.link_threshold, ledger=ledger)
        picks.update(ids)
    calls = [asdict(m) for m in ledger]
    return {"effort": effort or "default", "picks": picks, "calls": calls,
            "cost_usd": round(sum(m.cost_usd for m in ledger), 4)}  # fmt: skip


async def main() -> int:
    graph = ConceptGraph(ConceptGraphFile.model_validate_json(GRAPH.read_bytes()))
    default = await run(None, graph)
    low = await run("low", graph)
    a, b = default["picks"], low["picks"]
    agree = sum(a.get(n) == b.get(n) for n in a)
    result = {
        "time": datetime.now(UTC).isoformat(timespec="seconds"),
        "graph": graph.version,
        "default": default,
        "low": low,
        "agreement": {"agree": agree, "of": len(a), "share": round(agree / max(1, len(a)), 3)},
        "differences": {
            n: [a.get(n), b.get(n)] for n in sorted(set(a) | set(b)) if a.get(n) != b.get(n)
        },
        "passed": agree >= PASS_AGREEMENT * len(a),
    }
    out = ROOT / "results" / f"resolve-effort-{datetime.now(UTC):%Y%m%dT%H%M%S%z}.json"
    out.write_text(json.dumps(result, indent=1) + "\n")
    print(json.dumps({k: result[k] for k in ("agreement", "differences", "passed")}, indent=1))
    for r in (default, low):
        lc = [c for c in r["calls"] if c["task"] == "link_confirm"]
        print(r["effort"], "latency ms", sorted(round(c["latency_ms"]) for c in lc),
              "fell back", sum(c["fell_back"] for c in lc), "cost", r["cost_usd"])  # fmt: skip
    print("saved", out.relative_to(ROOT.parent))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
