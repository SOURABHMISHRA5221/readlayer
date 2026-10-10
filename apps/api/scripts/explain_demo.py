"""Demo evidence for M5, written to evals/demo.md:

1. "Depth adapts": basis points, where the three personas sit at different bands, so the
   Background changes depth (a trader who can explain it gets nuance, not a definition).
2. "Three frames": credit default swap, unfamiliar to all three, so each gets a full Background
   with an analogy from their own frame (software, cricket, law).
3. One real case where the verifier rejected a draft (from the saved eval runs).

    uv run python -m scripts.explain_demo

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
# (content id, demand id, heading, what it shows). Both spans are annotated for all three
# personas (checked with the scorer on the seeded templates).
EXHIBITS = (
    (
        "2332418841faa08d5f5e157c2d038d1d",  # Economic Times markets preview, "bps"
        "d6",
        "Depth adapts",
        "Bands differ (newcomer unaware, trader can explain, policy student heard of), so the "
        "Background changes depth: the trader gets nuance, not a definition.",
    ),
    (
        "99a2cb53f16256bd275bafd180364134",  # The Guardian, Polymarket bets on HSBC
        "d11",
        "Three frames",
        "Unfamiliar to all three (unaware or heard of), so each gets a full Background with an "
        "analogy from their own frame.",
    ),
)
READ_ONLY_UID = "demo-readonly"  # load_state only reads; nothing is written for this uid


def _cell(text: str | None) -> str:
    return (text or "–").replace("|", "\\|").replace("\n", " ")


async def personas_side_by_side(
    content_id: str, demand_id: str, heading: str, shows: str
) -> list[str]:
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
        f"## {heading}: *{first.label}*",
        "",
        shows,
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
    frames = [r["outcome"].explanation.analogy_domain if r["outcome"].explanation else None
              for r in rows]  # fmt: skip
    lines.append("| Analogy used | " + " | ".join(f or "none" for f in frames) + " |")
    cost = sum(r["outcome"].cost_usd for r in rows)
    lines += ["", f"Generated {now:%Y-%m-%d %H:%M} UTC, prompts {service.prompt_version()}, "
              f"cost ${cost:.4f} for the three cards."]  # fmt: skip
    return lines


def _rejections() -> list[tuple[int, str, dict[str, Any], dict[str, Any]]]:
    """(preference, run file, run, case) for every case with a rejected draft. Preferred: the
    judge caught it on a real-article case (pipeline), the newest run first."""
    found = []
    for age, path in enumerate(sorted(RESULTS.glob("*.json"), reverse=True)):
        run = json.loads(path.read_text(encoding="utf-8"))
        for part in ("pipeline", "injection"):
            for case in run.get(part, []):
                rejected = [a for a in case["attempts"] if a["reasons"]]
                if not rejected:
                    continue
                by_judge = any(r.startswith("judge_") for r in rejected[0]["reasons"])
                rank = (0 if part == "pipeline" else 2) + (0 if by_judge else 1)
                found.append((rank * 100 + age, path.name, run, case))
    return sorted(found, key=lambda f: f[0])


def rejection_example() -> list[str]:
    found = _rejections()
    if not found:
        return ["## A draft the verifier rejected", "", "No rejected draft in the saved runs yet."]
    _, name, run, case = found[0]
    bad = next(
        (a for a in case["attempts"] if a["reasons"] and a["draft"].get("author_says")),
        next(a for a in case["attempts"] if a["reasons"]),
    )
    lines = [
        "## A draft the verifier rejected",
        "",
        f"Eval case `{case['id']}` in `{name}` (judge `{run['meta']['judge_model']}`, prompts "
        f"`{run['meta']['prompt_version']}`). Outcome: **{case['kind']}** ({case['reason']}).",
        "",
        "**Rejected draft, What the author is saying:**",
        "",
        f"> {bad['draft'].get('author_says') or bad['draft'].get('background')}",
        "",
        "**Why:**",
        "",
        *[f"- {r}" for r in bad["reasons"]],
    ]
    if case["final"]:
        lines += ["", "**Accepted retry:**", "", f"> {case['final']['author_says']}"]
    else:
        lines += ["", "No retry passed, so the reader saw the definition only."]
    return lines


async def exhibits() -> list[str]:
    out: list[str] = []
    for content_id, demand_id, heading, shows in EXHIBITS:
        out += [*await personas_side_by_side(content_id, demand_id, heading, shows), ""]
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--rejection-only", action="store_true", help="rewrite only the rejection section"
    )
    if parser.parse_args().rejection_only:
        text = OUT.read_text(encoding="utf-8")
        head = text.split("## A draft the verifier rejected")[0]
        OUT.write_text(head + "\n".join(rejection_example()) + "\n", encoding="utf-8")
        print("\n".join(rejection_example()))
        return
    body = [
        "# Explanation demo (M5)",
        "",
        "Generated by `uv run python -m scripts.explain_demo` with the shipped prompts, through "
        "the same generate → checks → judge pipeline as the API (persona templates read-only, "
        "nothing cached). Reader bands come from the seeded persona templates.",
        "",
        *asyncio.run(exhibits()),
        *rejection_example(),
        "",
    ]
    OUT.write_text("\n".join(body), encoding="utf-8")
    print("\n".join(body))
    print(f"\nwrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
