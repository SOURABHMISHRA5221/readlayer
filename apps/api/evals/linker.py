"""Linker eval suite (M2.2, plan §D.6–D.7, §E.6). From apps/api, with the project's ADC:

    uv run python -m evals.run --suite linker --label before

Three parts, all on frozen cases (committed before any model run, decision 26):
1. link_confirm regression cases (cases/link_confirm.yaml): pass when the model's pick is one of
   `expect`, or null when `expect` is empty.
2. Variant precision (cases/link_variants.yaml): each frozen mention is asked with its embedding
   candidates (alias shortcut off, LINK_THRESHOLD floor); precision = correct / (correct + wrong).
3. link_merge agreement (cases/link_merge.yaml): the model's same/not-same vs the M2 decision.

Model and embedding calls go through the build cache, keyed by prompt version, so a rerun of the
same prompt is free and a new prompt version is a fresh run. Results go to evals/results/.
"""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from app import llm
from app.config import get_settings
from app.graph import enrich, jurisdiction
from app.graph.enrich import Entry, LinkQuestion
from app.graph.graph import ConceptGraph
from app.graph.linking import CANDIDATES, phrase, sentence_around
from app.graph.models import ConceptGraphFile
from scripts.build_cache import BuildCache
from scripts.build_concepts import CACHE_DIR, CONCEPTS_FILE

ROOT = Path(__file__).parent
CASES = ROOT / "cases"
RESULTS = ROOT / "results"
LINK_THRESHOLD = 0.865  # fixed for every M2.2 run (plan §B.3 step 10)


def load(name: str) -> list[dict[str, Any]]:
    return yaml.safe_load((CASES / f"{name}.yaml").read_text(encoding="utf-8"))


def case_question(case: dict[str, Any], filtered: bool = True) -> LinkQuestion:
    """The question the linker would ask. With `filtered`, the code jurisdiction filter runs
    first (as plan_links does), so the suite tests the whole linker, not only the prompt."""
    sentence = " ".join(case["sentence"].split())
    site = case.get("site", "")
    article = jurisdiction.cues(site, "", sentence)
    cands = [
        c
        for c in case["candidates"]
        if not filtered
        or jurisdiction.allowed(c.get("kind"), c.get("jurisdiction") or "global", article)
    ]
    return LinkQuestion(
        case["id"],
        case["phrase"],
        sentence,
        tuple((c["id"], c["label"], c["definition"], 1.0) for c in cands),
        site=site,
        kinds=tuple(c.get("kind") or "" for c in cands),
        jurisdictions=tuple(c.get("jurisdiction") or "global" for c in cands),
        article=tuple(sorted(article)),
    )


def score_case(case: dict[str, Any], pick: str | None) -> bool:
    return pick in case["expect"] if case["expect"] else pick is None


async def run_link_confirm(cache: BuildCache, ledger: list) -> list[dict[str, Any]]:
    cases = load("link_confirm")
    questions = [case_question(c) for c in cases]
    asked = [i for i, q in enumerate(questions) if q.candidates]  # all filtered out → null
    got = await enrich.confirm_links([questions[i] for i in asked], cache.run, ledger)
    answers = {asked[k]: v for k, v in got.items()}
    out = []
    for i, c in enumerate(cases):
        pick = answers.get(i)
        out.append(
            {"id": c["id"], "pick": pick, "expect": c["expect"], "passed": score_case(c, pick)}
        )
    return out


async def run_variants(graph: ConceptGraph, cache: BuildCache, ledger: list) -> dict[str, Any]:
    from scripts.build_concepts import load_docs

    rows = load("link_variants")
    docs = {d.content_id: d for d in await load_docs()}
    labels = sorted({r["label"] for r in rows})
    vecs = dict(zip(labels, await cache.embed(labels, "SEMANTIC_SIMILARITY"), strict=True))
    questions, kept = [], []
    for r in rows:
        doc = docs.get(r["content_id"])
        demand = next((d for d in doc.demands if d.id == r["demand_id"]), None) if doc else None
        if demand is None:
            continue
        para = next((p.text for p in doc.paragraphs if p.id == demand.paragraph_id), "")
        near = graph.nearest(vecs[r["label"]], CANDIDATES)
        article = jurisdiction.cues(doc.site, doc.final_url or doc.url, para)
        cands = tuple(
            (c.id, c.label, c.definition, s)
            for c, s in near
            if s >= LINK_THRESHOLD and jurisdiction.allowed(c.kind, c.jurisdiction, article)
        )
        questions.append(
            LinkQuestion(
                demand.id,
                phrase(demand),
                sentence_around(para, demand.anchor.exact, demand.anchor.prefix),
                cands,
                site=doc.site,
                kinds=tuple(graph.get(cid).kind or "" for cid, *_ in cands),
                jurisdictions=tuple(graph.get(cid).jurisdiction for cid, *_ in cands),
                article=tuple(sorted(article)),
            )
        )
        kept.append(r)
    asked = [i for i, q in enumerate(questions) if q.candidates]
    answers = await enrich.confirm_links([questions[i] for i in asked], cache.run, ledger)
    picks = {asked[k]: v for k, v in answers.items()}
    counts = {"correct": 0, "wrong": 0, "none": 0}
    for i, r in enumerate(kept):
        pick = picks.get(i)
        counts["none" if pick is None else "correct" if pick == r["target"] else "wrong"] += 1
    decided = counts["correct"] + counts["wrong"]
    return {
        **counts,
        "n": len(kept),
        "missing": len(rows) - len(kept),
        "precision": round(counts["correct"] / decided, 4) if decided else None,
    }


async def run_merges(cache: BuildCache, ledger: list) -> dict[str, Any]:
    rows = load("link_merge")
    pairs = [(Entry(r["a"]), Entry(r["b"])) for r in rows]
    answers = await enrich.check_merges(pairs, cache.run, ledger)
    agree = sum(answers.get(i) == r["same"] for i, r in enumerate(rows))
    return {
        "n": len(rows),
        "agree_with_m2": agree,
        "answers": [answers.get(i) for i in range(len(rows))],
    }


async def run_suite(graph_path: Path = CONCEPTS_FILE) -> dict[str, Any]:
    settings = get_settings()
    cache = BuildCache(CACHE_DIR, settings)
    ledger: list = []
    raw = await asyncio.to_thread(graph_path.read_bytes)
    graph = ConceptGraph(ConceptGraphFile.model_validate_json(raw))
    confirm = await run_link_confirm(cache, ledger)
    variants = await run_variants(graph, cache, ledger)
    merges = await run_merges(cache, ledger)
    return {
        "meta": {
            "time": datetime.now(UTC).isoformat(timespec="seconds"),
            "graph": graph.version,
            "prompts": {t: llm.load_prompt(t).version for t in ("link_confirm", "link_merge")},
            "link_threshold": LINK_THRESHOLD,
            "cost_usd": round(cache.llm_cost_new + cache.embed_cost_new, 4),
            "cost_cached_usd": round(cache.llm_cost_cached, 4),
            # answers from MODEL_FALLBACK (an outage, not the prompt); the build cache re-asks
            # them on the next run, so a rerun replaces only those batches.
            "fallbacks": sum(1 for m in ledger if m.fell_back),
            "calls": len(ledger),
        },
        "link_confirm": confirm,
        "variants": variants,
        "merges": merges,
        "summary": {
            "link_confirm_passed": sum(c["passed"] for c in confirm),
            "link_confirm_total": len(confirm),
            "variant_precision": variants["precision"],
            "merge_agreement": merges["agree_with_m2"],
            "merge_total": merges["n"],
        },
    }


def save(results: dict[str, Any], label: str) -> Path:
    RESULTS.mkdir(exist_ok=True)
    stamp = results["meta"]["time"].replace(":", "").replace("-", "")
    path = RESULTS / f"linker-{stamp}-{label}.json"
    results["meta"]["label"] = label
    path.write_text(json.dumps(results, indent=1) + "\n", encoding="utf-8")
    return path
