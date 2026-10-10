"""M2.2 held-out headline: frozen-graph link rate per domain on the 30 held-out articles.

    cd apps/api && uv run python -m scripts.heldout_headline --label before [--graph PATH]

Number 1 of decision 34. Every concept/term demand of the 30 held-out articles is re-linked IN
MEMORY with the current linker against a fixed graph file (default data/concepts.json); no doc
is rewritten and nothing grows. The old 15 use their stored demands (Firestore, read-only); the
new 15 use the frozen set (data/heldout_new_demands.json, sha256-checked) with their paragraphs
from the gitignored build cache (per-doc sha256-checked). LINK_THRESHOLD is fixed at 0.865.

Each run appends a row block to evals/heldout_report.md under "Run log" (every run, in order;
no picking the best one) and saves evals/results/heldout-<stamp>-<label>.json.
"""

import argparse
import asyncio
import hashlib
import json
import random
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app import llm
from app.config import get_settings
from app.graph import enrich
from app.graph.graph import ConceptGraph
from app.graph.grow import grow
from app.graph.linking import EMBED_TYPES, link_demands, sentence_around
from app.graph.models import ConceptGraphFile
from app.graph.taxonomy import BUSINESS_DOMAINS
from app.ingest.models import Demand
from app.ingest.urls import url_hash
from app.log import configure_logging
from app.store.content_repo import get_content_store
from app.store.docstore import InMemoryDocStore
from app.store.growth_repo import GrowthRepo
from scripts.build_cache import BuildCache
from scripts.build_concepts import CACHE_DIR, CONCEPTS_FILE
from scripts.eval_heldout import HELDOUT_TARGET, read_heldout
from scripts.freeze_heldout_demands import (
    FREEZE_FILE,
    SHA_FILE,
    TEXT_DIR,
    file_sha,
    paragraphs_sha,
)

LINK_THRESHOLD = 0.865  # plan §B.3 step 10: fixed for every M2.2 run
EVALS = Path(__file__).parents[1] / "evals"
REPORT = EVALS / "heldout_report.md"
RESULTS = EVALS / "results"
REPORT_HEAD = """# Held-out linker evaluation (M2.2, decision 34)

30 held-out articles, never used to build the graph: lines 1–15 are the M2.1 business set,
lines 16–30 the M2.2 non-business set (domains fixed in data/heldout_urls.txt before any run).
Number 1, the headline, is the **frozen-graph** link rate: every concept/term demand re-linked in
memory against a fixed graph file, no growth. Targets: business ≥ 75%, non-business aim 60%,
under 50% (total or any domain) stops the milestone for Sourabh. The **new 15** row is untouched
by any tuning; the old 15 informed the M2.2 fixes (Chancellor, levy, Russell examples).
LINK_THRESHOLD 0.865 for every run.

## Run log (every run, in order)
"""


def prod_threshold() -> float:
    """The threshold production links with (Cloud Run env from deploy.env.yaml)."""
    import yaml

    env = yaml.safe_load((Path(__file__).parents[1] / "deploy.env.yaml").read_text())
    return float(env["LINK_THRESHOLD"])


def _verify_freeze() -> dict[str, Any]:
    recorded = SHA_FILE.read_text().split()[0]
    if file_sha(FREEZE_FILE) != recorded:
        raise SystemExit("heldout_new_demands.json changed since it was frozen")
    return json.loads(FREEZE_FILE.read_text(encoding="utf-8"))


async def load_docs() -> list[dict[str, Any]]:
    """[{content_id, domain, group, paragraphs: {id: text}, demands: [Demand]}] for all 30."""
    entries = read_heldout()
    content = get_content_store()
    out = []
    for e in entries[:HELDOUT_TARGET]:
        doc = await content.get(url_hash(e.url))
        if doc is None:
            raise SystemExit(f"old held-out doc missing: {e.url}")
        out.append(
            {
                "content_id": doc.content_id,
                "site": doc.site,
                "url": doc.final_url or doc.url,
                "domain": e.domain,
                "group": "old",
                "paragraphs": {p.id: p.text for p in doc.paragraphs},
                "demands": [d.model_copy(update={"target_id": None}) for d in doc.demands],
            }
        )
    for frozen in _verify_freeze()["docs"]:
        cached = json.loads((TEXT_DIR / f"{frozen['content_id']}.json").read_text("utf-8"))
        texts = [p["text"] for p in cached["paragraphs"]]
        if paragraphs_sha(texts) != frozen["paragraphs_sha256"]:
            raise SystemExit(f"cached paragraphs changed for {frozen['url']}")
        out.append(
            {
                "content_id": frozen["content_id"],
                "site": cached.get("site") or "",
                "url": cached.get("final_url") or frozen["url"],
                "domain": frozen["domain"],
                "group": "new",
                "paragraphs": {p["id"]: p["text"] for p in cached["paragraphs"]},
                "demands": [Demand.model_validate(d) for d in frozen["demands"]],
            }
        )
    return out


def rate(c: Counter[str]) -> str:
    n = sum(c.values())
    linked = c["alias"] + c["confirmed"] + c["grown"]
    return f"{linked / n:.0%}" if n else "–"


def table(rows: dict[str, Counter[str]], grown: bool = False) -> list[str]:
    kinds = (
        ("alias", "confirmed", "grown", "unlinked") if grown else ("alias", "confirmed", "unlinked")
    )
    names = {"alias": "exact-name", "confirmed": "model-confirmed", "grown": "grown here",
             "unlinked": "unlinked"}  # fmt: skip
    out = [
        "| group | n | " + " | ".join(names[k] for k in kinds) + " | **linked** |",
        "|---|---|" + "---|" * len(kinds) + "---|",
    ]
    for name, c in rows.items():
        n = sum(c.values())
        cells = [f"{c[k]} ({c[k] / n:.0%})" if n else "0" for k in kinds]
        out.append(f"| {name} | {n} | " + " | ".join(cells) + f" | **{rate(c)}** |")
    return out


def summarise(per_doc: list[dict[str, Any]]) -> dict[str, Counter[str]]:
    rows: dict[str, Counter[str]] = {}

    def add(key: str, c: Counter[str]) -> None:
        rows.setdefault(key, Counter()).update(c)

    for d in per_doc:
        group = "business" if d["domain"] in BUSINESS_DOMAINS else "non-business"
        add(f"{group} (total)", d["counts"])
        add(f"  {d['domain']}", d["counts"])
        if d["group"] == "new":
            add("new 15 (untuned)", d["counts"])
        add("all 30", d["counts"])
    order = ["business (total)", "non-business (total)", "new 15 (untuned)", "all 30"]
    domains = sorted(k for k in rows if k.startswith("  "))
    return {k: rows[k] for k in order + domains if k in rows}


def stop_check(rows: dict[str, Counter[str]]) -> list[str]:
    """Decision 34: business < 75%, non-business total < 50% or any non-business domain < 50%."""

    def pct(c: Counter[str]) -> float:
        n = sum(c.values())
        return (c["alias"] + c["confirmed"]) / n if n else 1.0

    problems = []
    if pct(rows.get("business (total)", Counter())) < 0.75:
        problems.append("business under 75%")
    if pct(rows.get("non-business (total)", Counter())) < 0.50:
        problems.append("non-business total under 50%")
    for key, c in rows.items():
        name = key.strip()
        if key.startswith("  ") and name not in BUSINESS_DOMAINS and pct(c) < 0.50:
            problems.append(f"{name} under 50% (n={sum(c.values())})")
    return problems


GROWTH_SAMPLE = 30
GROWTH_SEED = 34  # decision 34


async def run(graph_path: Path, label: str, with_growth: bool = False) -> dict[str, Any]:
    settings = get_settings()
    if prod_threshold() != LINK_THRESHOLD:
        raise SystemExit(f"deploy.env.yaml LINK_THRESHOLD is {prod_threshold()}, M2.2 fixes 0.865")
    cache = BuildCache(CACHE_DIR, settings)
    ledger: list[llm.CallMeta] = []
    raw = await asyncio.to_thread(graph_path.read_bytes)
    graph = ConceptGraph(ConceptGraphFile.model_validate_json(raw))

    async def embed(texts: list[str]) -> list[list[float]]:
        return await cache.embed(texts, "SEMANTIC_SIMILARITY")

    async def confirm(questions):
        return await enrich.confirm_links(questions, cache.run, ledger)

    per_doc: list[dict[str, Any]] = []
    grown_all: list[dict[str, Any]] = []
    growth_graph = graph
    growth_repo = GrowthRepo(InMemoryDocStore())  # held-out text never grows the real graph
    for doc in await load_docs():
        linked, links = await link_demands(
            graph,
            doc["demands"],
            doc["paragraphs"],
            LINK_THRESHOLD,
            embed=embed,
            confirm=confirm,
            site=doc["site"],
            url=doc["url"],
        )
        types = {d.id: d.type for d in doc["demands"]}
        counts = Counter(lk.method for lk in links if types[lk.demand_id] in EMBED_TYPES)
        row = {**{k: doc[k] for k in ("content_id", "domain", "group")}, "counts": counts}
        if with_growth:
            growth_graph = await _grow_one(
                doc, linked, links, types, counts, row, growth_graph, growth_repo,
                cache, ledger, embed, grown_all,
            )  # fmt: skip
        per_doc.append(row)
    rows = summarise(per_doc)
    after_rows = (
        summarise([{**d, "counts": d["after_growth"]} for d in per_doc]) if with_growth else {}
    )
    sample = random.Random(GROWTH_SEED).sample(grown_all, min(GROWTH_SAMPLE, len(grown_all)))
    return {
        "meta": {
            "label": label,
            "time": datetime.now(UTC).isoformat(timespec="seconds"),
            "graph": graph.version,
            "graph_sha256": hashlib.sha256(raw).hexdigest()[:16],
            "concepts": len(graph),
            "link_confirm": llm.load_prompt("link_confirm").version,
            "link_threshold": LINK_THRESHOLD,
            "cost_usd": round(cache.llm_cost_new + cache.embed_cost_new, 4),
            "fallbacks": sum(1 for m in ledger if m.fell_back),
        },
        "rows": {k: dict(v) for k, v in rows.items()},
        "after_growth_rows": {k: dict(v) for k, v in after_rows.items()},
        "per_doc": [
            {**d, "counts": dict(d["counts"]), "after_growth": dict(d.get("after_growth", {}))}
            for d in per_doc
        ],
        "grown": grown_all,
        "grown_sample": sample,
        "stop": stop_check(rows),
    }


async def _grow_one(doc, linked, links, types, counts, row, graph, repo, cache, ledger, embed,
                    grown_all) -> ConceptGraph:  # fmt: skip
    """Number 2 for one article: grow from it, in order, against the in-memory graph so far."""
    outcome = await grow(
        graph, linked, doc["paragraphs"], get_settings().growth_per_article,
        doc["content_id"], repo, cache.run, embed,
    )  # fmt: skip
    ledger.extend(outcome.calls)
    new_graph = graph.with_concepts(outcome.added, f"{graph.version.split('+')[0]}+held")
    moved = {lk.demand_id for lk in links
             if lk.method == "unlinked" and lk.demand_id in outcome.links
             and types[lk.demand_id] in EMBED_TYPES}  # fmt: skip
    grown_ids = moved & outcome.grown
    after = Counter(counts)
    after["unlinked"] -= len(moved)
    after["confirmed"] += len(moved - grown_ids)  # merged into an existing concept
    after["grown"] += len(grown_ids)
    row["after_growth"] = after
    by_id = {d.id: d for d in linked}
    for c in outcome.added:
        did = next((d for d, cid in outcome.links.items() if cid == c.id), None)
        trigger = by_id.get(did) if did else None
        sentence = (
            sentence_around(doc["paragraphs"].get(trigger.paragraph_id, ""), trigger.anchor.exact)
            if trigger else None
        )  # fmt: skip
        grown_all.append({
            "content_id": doc["content_id"],
            "domain_label": doc["domain"],
            "concept": c.model_dump(exclude={"embedding"}),
            "prerequisite_labels": [new_graph.get(p).label for p in c.prerequisites
                                    if new_graph.get(p)],
            "trigger": trigger.anchor.exact if trigger else None,
            "sentence": sentence,
        })  # fmt: skip
    return new_graph


def append_report(result: dict[str, Any]) -> None:
    m = result["meta"]
    text = REPORT.read_text(encoding="utf-8") if REPORT.exists() else REPORT_HEAD
    block = [
        "",
        f"### {m['time']} · {m['label']}",
        "",
        f"Graph {m['graph']} ({m['concepts']} concepts, sha {m['graph_sha256']}), "
        f"{m['link_confirm']}, threshold {m['link_threshold']}, new spend ${m['cost_usd']:.4f}, "
        f"model fallbacks {m['fallbacks']}.",
        "",
        *table({k: Counter(v) for k, v in result["rows"].items()}),
        "",
        "Stop check: " + ("; ".join(result["stop"]) if result["stop"] else "pass"),
    ]
    if result.get("after_growth_rows"):
        rows = {k: Counter(v) for k, v in result["after_growth_rows"].items()}
        block += [
            "",
            "**Number 2, after growth (production behaviour: includes concepts grown from the "
            "article itself; never the headline):**",
            "",
            *table(rows, grown=True),
            "",
            f"Concepts grown in memory: {len(result['grown'])}; a seeded sample of "
            f"{len(result['grown_sample'])} is saved with the run for Number 3 (verdicts below).",
        ]
    REPORT.write_text(text.rstrip("\n") + "\n" + "\n".join(block) + "\n", encoding="utf-8")


async def main(args: argparse.Namespace) -> int:
    configure_logging("WARNING")
    result = await run(Path(args.graph), args.label, args.growth)
    RESULTS.mkdir(exist_ok=True)
    stamp = result["meta"]["time"].replace(":", "").replace("-", "")
    (RESULTS / f"heldout-{stamp}-{args.label}.json").write_text(
        json.dumps(result, indent=1) + "\n", encoding="utf-8"
    )
    append_report(result)
    print("\n".join(table({k: Counter(v) for k, v in result["rows"].items()})))
    print(f"stop check: {result['stop'] or 'pass'} · meta {result['meta']}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--graph", default=str(CONCEPTS_FILE))
    parser.add_argument("--growth", action="store_true", help="also Numbers 2 and 3 (in memory)")
    sys.exit(asyncio.run(main(parser.parse_args())))
