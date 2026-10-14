"""M9 part 2, R3: the real model on the in-batch merge question, before it ships.

    uv run python -m scripts.replay_merges

Reads the blind verdicts (`evals/merge_verdicts.json`, committed before this ran), asks
`link_merge` (MODEL_FAST, through llm.py) about every pair exactly as growth will ask about two
picks of one batch (two bare labels), and writes `evals/merge_replay.md`: the model's answer beside
each verdict, false merges and missed duplicates. Writes nothing else but the spend ledger.
"""

import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path

EVALS = Path(__file__).resolve().parents[1] / "evals"
DUPLICATE_COSINE = 0.899  # Forever chemicals / PFAS: no threshold may rise past it (S1)


@dataclass(frozen=True)
class Row:
    a: str
    b: str
    cosine: float
    verdict: str  # "same" | "different", judged blind
    model_same: bool


def report(rows: list[Row], cost_usd: float) -> str:
    false_merges = [r for r in rows if r.model_same and r.verdict != "same"]
    missed = [r for r in rows if not r.model_same and r.verdict == "same"]
    above = [r for r in false_merges if r.cosine >= DUPLICATE_COSINE]
    lines = [
        "# In-batch merge replay (M9 part 2, R3)",
        "",
        "Same-page pairs of production grown concepts with label cosine ≥ 0.85 (added_at ≤",
        "2026-10-14 09:24:55 UTC). Verdicts were judged blind by the implementing agent and",
        "committed (`merge_verdicts.json`, 9e4e138) before the model was asked. The model is asked",
        "exactly as growth asks about two picks of one batch: `link_merge` on MODEL_FAST, two bare",
        f"labels. Cost ${cost_usd:.4f}.",
        "",
        f"**{len(rows)} pairs: false merges {len(false_merges)} "
        f"({len(above)} at cosine ≥ {DUPLICATE_COSINE}), missed duplicates {len(missed)}.**",
        "",
        "| cosine | a | b | verdict (blind) | model | |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        mark = "" if r.model_same == (r.verdict == "same") else "**disagree**"
        model = "same" if r.model_same else "different"
        lines.append(f"| {r.cosine:.3f} | {r.a} | {r.b} | {r.verdict} | {model} | {mark} |")
    return "\n".join(lines) + "\n"


async def main() -> int:
    from app import llm
    from app.graph import enrich

    data = json.loads((EVALS / "merge_verdicts.json").read_text(encoding="utf-8"))
    pairs = data["pairs"]
    ledger: list[llm.CallMeta] = []
    answers = await enrich.check_merges(
        [(enrich.Entry(p["a"]), enrich.Entry(p["b"])) for p in pairs], llm.run_with_meta, ledger
    )
    rows = [
        Row(p["a"], p["b"], p["cosine"], p["verdict"], bool(answers.get(i)))
        for i, p in enumerate(pairs)
    ]
    out = report(rows, sum(m.cost_usd for m in ledger))
    (EVALS / "merge_replay.md").write_text(out, encoding="utf-8")
    print(out.split("\n\n")[2])
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
