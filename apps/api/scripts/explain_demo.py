"""Demo evidence for M5: one concept on one article, explained for the three personas side by
side, plus one real case where the verifier rejected a draft (from the saved eval runs).

    uv run python -m scripts.explain_demo [--content-id ID --demand-id D]

Reads the persona templates and the article (read-only), makes up to ~12 model calls through
app/llm.py (budget guard on), and writes evals/demo.md. Nothing is cached or written to
Firestore apart from the spend ledger.
"""

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.explain import service
from app.explain.inputs import span_inputs
from app.graph.loader import load_graph
from app.reader.personas import PERSONA_THINKS_IN, PERSONAS
from app.reader.state import PERSONA_KEYS
from app.store.content_repo import FirestoreContentStore
from app.store.docstore import FirestoreDocStore
from app.store.reader_repo import ReaderRepo

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evals" / "demo.md"
RESULTS = ROOT / "evals" / "results"
# Economic Times markets preview, "bps" (basis points): a span for all three personas, at
# bands unaware (newcomer), can explain (trader), heard of (policy student).
DEFAULT_CONTENT = "2332418841faa08d5f5e157c2d038d1d"
DEFAULT_DEMAND = "d6"
READ_ONLY_UID = "demo-readonly"  # load_state only reads; nothing is written for this uid


def _cell(text: str | None) -> str:
    return (text or "–").replace("|", "\\|").replace("\n", " ")


async def personas_side_by_side(content_id: str, demand_id: str) -> list[str]:
    settings = get_settings()
    graph = await load_graph(settings.concepts_uri)
    doc = await FirestoreContentStore(settings.gcp_project).get(content_id)
    if doc is None:
        raise SystemExit(f"content {content_id} not found")
    demand = next(d for d in doc.demands if d.id == demand_id)
    repo = ReaderRepo(FirestoreDocStore(settings.gcp_project))
    now = datetime.now(UTC)
    rows: list[dict[str, Any]] = []
    for persona in PERSONA_KEYS:
        state, _, _ = await repo.load_state(READ_ONLY_UID, persona)
        inputs = span_inputs(doc, demand, graph, state, now, PERSONA_THINKS_IN[persona], "normal")
        if inputs is None:
            raise SystemExit("demand is not linked to a concept")
        outcome = await service.generate_verified(inputs)
        rows.append({"persona": persona, "inputs": inputs, "outcome": outcome})
    first = rows[0]["inputs"]
    lines = [
        f"## One concept, three readers: *{first.label}*",
        "",
        f"Article: **{doc.title}** ({doc.site}). Span: “{demand.anchor.exact}”.",
        "",
        f"> {first.sentence}",
        "",
        "| | " + " | ".join(PERSONAS[r["persona"]].label for r in rows) + " |",
        "|---|" + "---|" * len(rows),
        "| Band for this concept | " + " | ".join(r["inputs"].band for r in rows) + " |",
        "| Analogy frame | " + " | ".join(r["inputs"].thinks_in or "none" for r in rows) + " |",
        "| Outcome | "
        + " | ".join(f"{r['outcome'].kind} ({r['outcome'].reason})" for r in rows)
        + " |",
    ]
    for label, attr in (("Background", "background"), ("What the author is saying", "author_says")):
        cells = [
            _cell(getattr(r["outcome"].explanation, attr) if r["outcome"].explanation else None)
            for r in rows
        ]
        lines.append(f"| **{label}** | " + " | ".join(cells) + " |")
    cost = sum(r["outcome"].cost_usd for r in rows)
    lines += ["", f"Generated {now:%Y-%m-%d %H:%M} UTC, prompts {service.prompt_version()}, "
              f"cost ${cost:.4f} for the three cards."]  # fmt: skip
    return lines


def rejection_example() -> list[str]:
    """The first pipeline or injection case in the newest run where a draft was rejected."""
    for path in sorted(RESULTS.glob("*.json"), reverse=True):
        run = json.loads(path.read_text(encoding="utf-8"))
        for case in run.get("pipeline", []) + run.get("injection", []):
            rejected = [a for a in case["attempts"] if a["reasons"]]
            if not rejected:
                continue
            bad = rejected[0]
            lines = [
                "## A draft the verifier rejected",
                "",
                f"Eval case `{case['id']}` in `{path.name}` (judge `{run['meta']['judge_model']}`)."
                f" Outcome: **{case['kind']}** ({case['reason']}).",
                "",
                "**Rejected draft, What the author is saying:**",
                "",
                f"> {bad['draft']['author_says']}",
                "",
                "**Why:**",
                "",
                *[f"- {r}" for r in bad["reasons"]],
            ]
            if case["final"]:
                lines += [
                    "",
                    "**Accepted retry:**",
                    "",
                    f"> {case['final']['author_says']}",
                ]
            else:
                lines += ["", "No retry passed, so the reader saw the definition only."]
            return lines
    return ["## A draft the verifier rejected", "", "No rejected draft in the saved runs yet."]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--content-id", default=DEFAULT_CONTENT)
    parser.add_argument("--demand-id", default=DEFAULT_DEMAND)
    args = parser.parse_args()
    side = asyncio.run(personas_side_by_side(args.content_id, args.demand_id))
    body = ["# Explanation demo (M5)", "", *side, "", *rejection_example(), ""]
    OUT.write_text("\n".join(body), encoding="utf-8")
    print("\n".join(body))
    print(f"\nwrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
