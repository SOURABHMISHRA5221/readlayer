"""Onboarding topic fallback eval (decision 42). From apps/api, with the project's ADC:

    uv run python -m evals.onboarding_topics

Embeds the frozen phrases (cases/onboarding_topics.yaml, committed before this ran) and the 14
topic scope lines with MODEL_EMBED, exactly as POST /v1/onboarding/resolve does, then reports
precision and recall per threshold. ONBOARDING_TOPIC_THRESHOLD is the lowest threshold whose
precision is ≥ TARGET_PRECISION. One embed call per run (≈ 41 short texts).

`pipeline` scores the route's own topic order at the configured threshold: the alias list
(whole phrase), then word-level matching against the alias list and the production concept
graph (CONCEPTS_URI, read-only; no model call), then the embedding fallback. Phrases the
alias list copies verbatim are reported apart, since an alias hit on a test phrase says
nothing about unseen phrases.
"""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from app import llm
from app.config import get_settings
from app.graph.loader import load_graph
from app.reader.onboarding_text import alias_topic, nearest_topic, topic_texts, word_topic

ROOT = Path(__file__).parent
CASES = ROOT / "cases" / "onboarding_topics.yaml"
RESULTS = ROOT / "results" / "onboarding_topics"  # not results/*.json: report.py reads those
TARGET_PRECISION = 0.95
THRESHOLDS = [round(0.40 + 0.01 * i, 2) for i in range(51)]  # 0.40 … 0.90


def score(rows: list[dict[str, Any]], threshold: float) -> dict[str, Any]:
    correct = wrong = missed = 0
    for r in rows:
        mapped = r["topic"] if r["similarity"] >= threshold else None
        if mapped is None:
            missed += r["expect"] != "none"
        elif mapped == r["expect"]:
            correct += 1
        else:
            wrong += 1
    positives = sum(r["expect"] != "none" for r in rows)
    precision = correct / (correct + wrong) if correct + wrong else 1.0
    return {"threshold": threshold, "correct": correct, "wrong": wrong, "missed": missed,
            "precision": round(precision, 3), "recall": round(correct / positives, 3)}  # fmt: skip


async def main() -> dict[str, Any]:
    cases = yaml.safe_load(CASES.read_text(encoding="utf-8"))
    topics = topic_texts()
    result = await llm.embed(topics + [c["phrase"] for c in cases], task_type="SEMANTIC_SIMILARITY")
    topic_vecs, phrase_vecs = result.vectors[: len(topics)], result.vectors[len(topics) :]
    rows = []
    for case, vec in zip(cases, phrase_vecs, strict=True):
        topic, sim = nearest_topic(vec, topic_vecs, -1.0) or ("", 0.0)
        rows.append({"id": case["id"], "phrase": case["phrase"], "expect": case["expect"],
                     "topic": topic, "similarity": round(sim, 4)})  # fmt: skip
    sweep = [score(rows, t) for t in THRESHOLDS]
    settings = get_settings()
    threshold = settings.onboarding_topic_threshold
    graph = await load_graph(settings.concepts_uri)
    for r in rows:
        alias = alias_topic(r["phrase"])
        words = word_topic(graph, r["phrase"])
        emb = r["topic"] if r["similarity"] >= threshold else None
        r["words"] = f"{words.chunk} → {words.via}" if words else None
        r["via"] = "alias" if alias else "words" if words else "embedding" if emb else None
        r["mapped"] = alias or (words.topic if words else None) or emb
    ok = [s for s in sweep if s["precision"] >= TARGET_PRECISION and s["correct"]]
    chosen = ok[0] if ok else None
    return {
        "ran_at": datetime.now(UTC).isoformat(),
        "model": result.model,
        "cost_usd": result.cost_usd,
        "rows": rows,
        "sweep": sweep,
        "chosen": chosen,
        "pipeline": pipeline(rows, threshold),
    }


def pipeline(rows: list[dict[str, Any]], threshold: float) -> dict[str, Any]:
    def tally(rs: list[dict[str, Any]]) -> dict[str, Any]:
        pos = [r for r in rs if r["expect"] != "none"]
        right = sum(r["mapped"] == r["expect"] for r in pos)
        wrong = sum(r["mapped"] is not None and r["mapped"] != r["expect"] for r in rs)
        return {"recognised": f"{right}/{len(pos)}", "wrong": wrong,
                "by_alias": sum(r["via"] == "alias" for r in pos)}  # fmt: skip

    unseen = [r for r in rows if alias_topic(r["phrase"]) is None]
    return {"threshold": threshold, "all": tally(rows), "excluding_alias_copies": tally(unseen),
            "alias_copies": [r["phrase"] for r in rows if r not in unseen]}  # fmt: skip


if __name__ == "__main__":
    out = asyncio.run(main())
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / f"onboarding_topics_{datetime.now(UTC):%Y%m%dT%H%M%S}.json"
    path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    for r in sorted(out["rows"], key=lambda r: -r["similarity"]):
        mark = "ok" if r["topic"] == r["expect"] else "--"
        print(f"{r['similarity']:.3f}  {mark}  {r['id']}  {r['phrase']!r} → {r['topic']} "
              f"(expect {r['expect']})")  # fmt: skip
    print("chosen:", out["chosen"], "cost:", out["cost_usd"], "→", path)
    for r in out["rows"]:
        mark = (
            "ok"
            if r["mapped"] == r["expect"] or (r["mapped"] is None and r["expect"] == "none")
            else "--"
        )
        print(
            f"  {mark} {r['id']} {r['phrase']!r}: {r['mapped']} via {r['via']} [{r['words']}]"
            f" (expect {r['expect']})"
        )
    print("pipeline:", json.dumps(out["pipeline"]))
