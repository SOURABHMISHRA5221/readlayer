"""Markdown report for the M2 concept build (also printed to stdout)."""

import json
import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.graph import build
from app.graph.graph import ConceptGraph
from app.graph.linking import EMBED_TYPES, Link, sentence_around
from app.graph.models import ConceptGraphFile
from scripts.build_compare import INFLATED_NOTE, Previous, render_comparison
from scripts.ingest_corpus import STATE_FILE, load_state

__all__ = ["BuildResult", "DupResult", "Previous", "render"]

if TYPE_CHECKING:
    from scripts.build_concepts import Corpus, DedupeResult, LinkRun

SEED = 11


@dataclass
class DupResult:
    groups: list[list[int]]
    pairs: list[build.DuplicatePair]


@dataclass
class BuildResult:
    graph_file: ConceptGraphFile
    doc_freq: dict[str, int]  # concept id -> distinct duplicate groups mentioning it
    dedupe: "DedupeResult"
    dropped_kinds: dict[str, int]
    removed_edges: list[tuple[str, str]]
    with_qid: int
    fates: dict[str, str]  # normalised candidate label -> kept / dropped reason


def _pct(scores: list[float]) -> str:
    p = build.percentiles(scores)
    return " ".join(f"p{k}={v:.3f}" for k, v in p.items()) if p else "(none)"


def _section(title: str) -> list[str]:
    return ["", f"## {title}", ""]


def render(
    *,
    corpus: "Corpus",
    dup: DupResult,
    graph: ConceptGraph,
    result: BuildResult | None,
    link_run: "LinkRun",
    cache: Any,
    ledger: list,
    prev: Previous | None = None,
) -> str:
    rng = random.Random(SEED)
    out = [f"# M2 concept graph report — graph version {graph.version}"]
    out += _articles()
    out += _duplicates(corpus, dup)
    out += _concepts(graph, result)
    out += _chains(graph, rng)
    out += _calibration(link_run, result)
    out += _coverage(corpus, link_run)
    out += _spot_check(corpus, graph, link_run, rng)
    out += _costs(corpus, cache, ledger)
    if prev is not None:
        out += render_comparison(
            corpus=corpus, graph=graph, result=result, link_run=link_run, prev=prev, rng=rng
        )
    return "\n".join(out) + "\n"


def _articles() -> list[str]:
    state = load_state(STATE_FILE)
    by_source: dict[str, Counter[str]] = defaultdict(Counter)
    failures: list[str] = []
    for o in state.values():
        by_source[o.source][o.status] += 1
        if o.status == "failed":
            failures.append(f"- {o.source}: {o.code} {o.http_status or ''} — {o.url}")
    out = _section("Articles ingested")
    out += ["| source | ok | failed |", "|---|---|---|"]
    out += [f"| {s} | {c['ok']} | {c['failed']} |" for s, c in sorted(by_source.items())]
    total = sum(c["ok"] for c in by_source.values())
    out += ["", f"**Total ingested: {total}**", ""]
    out += ["Failures:" if failures else "Failures: none"] + failures
    return out


def _duplicates(corpus: "Corpus", dup: DupResult) -> list[str]:
    groups = [g for g in dup.groups if len(g) > 1]
    out = _section("Near-duplicate documents")
    out.append(
        f"{len(groups)} duplicate groups covering {sum(len(g) for g in groups)} docs "
        "(5-word-shingle Jaccard ≥ 0.5, or title+lead cosine ≥ 0.92 with Jaccard ≥ 0.15). "
        "Each group counts once for doc_freq."
    )
    pair_of = {(p.a, p.b): p for p in dup.pairs}
    for g in groups[:3]:
        a, b = sorted(g)[:2]
        p = pair_of.get((a, b))
        score = f" (cos {p.cosine:.3f}, jaccard {p.jaccard:.2f})" if p else ""
        out.append(f"- group of {len(g)}{score}:")
        for i in g[:3]:
            d = corpus.docs[i]
            out.append(f"  - [{corpus.source[d.content_id]}] {d.title}")
    return out


def _concepts(graph: ConceptGraph, result: BuildResult | None) -> list[str]:
    out = _section("Concepts")
    out.append(f"{len(graph)} concepts; prerequisite DAG acyclic: {graph.is_acyclic()}")
    if result is None:
        return out + ["(relink-only run: build statistics not recomputed)"]
    edges = sum(len(c.prerequisites) for c in graph.concepts)
    out.append(
        f"{edges} prerequisite edges; {len(result.removed_edges)} removed to break cycles; "
        f"dropped by kind: {json.dumps(result.dropped_kinds)}; "
        f"concepts with a Wikidata id: {result.with_qid}"
    )
    out += ["", "Top 20 by doc frequency (distinct duplicate groups):", ""]
    top = sorted(result.doc_freq.items(), key=lambda kv: -kv[1])[:20]
    out += [f"{i + 1}. {graph.get(cid).label} — {n}" for i, (cid, n) in enumerate(top)]
    return out


def _chains(graph: ConceptGraph, rng: random.Random) -> list[str]:
    with_prereqs = [c for c in graph.concepts if c.prerequisites]
    deep = [c for c in with_prereqs if len(graph.prerequisite_chain(c.id)) >= 3]
    pool = deep if len(deep) >= 10 else with_prereqs
    out = _section("Sample prerequisite chains (most basic first)")
    for c in rng.sample(pool, min(10, len(pool))):
        out.append("- " + " → ".join(x.label for x in graph.prerequisite_chain(c.id)))
    return out


def _calibration(link_run: "LinkRun", result: BuildResult | None) -> list[str]:
    out = _section("Threshold calibration")
    ev = link_run.eval_counts
    decided = ev["correct"] + ev["wrong"]
    precision = f"{ev['correct'] / decided:.0%}" if decided else "n/a"
    recall = f"{ev['correct'] / max(sum(ev.values()), 1):.0%}"
    hard_95 = build.calibrate_threshold(link_run.positives, link_run.hard_negatives, 0.95)
    out += [
        "Embedding similarity alone can't separate a concept from its nearest neighbours, so "
        "label embeddings only propose up to 5 candidates and the model picks one or none.",
        f"Evaluation set: exact-alias matches whose wording differs from the concept label "
        f"(n={len(link_run.positives)}), with the alias shortcut disabled.",
        f"- label cosine to the true concept: {_pct(link_run.positives)}",
        f"- best wrong concept, same mentions: {_pct(link_run.hard_negatives)}",
        f"- embedding-only threshold for 95% precision vs the best wrong concept: {hard_95}"
        " (would link almost nothing)",
        f"- LINK_THRESHOLD (candidate floor, keeps 95% of true matches): {link_run.threshold}",
        f"- true concept among the candidates: {link_run.topk_recall:.0%}",
        f"- full pipeline on {sum(ev.values())} sampled matches: {ev['correct']} correct, "
        f"{ev['wrong']} wrong, {ev['none']} none → precision {precision}, recall {recall}",
        f"- re-link: {link_run.questions} mentions sent to the model, "
        f"{link_run.changed_docs} docs updated",
    ]
    if result is None:
        return out
    dd = result.dedupe
    above = len(dd.accepted) + len(dd.rejected)
    band = len(dd.band_accepted) + len(dd.band_rejected)
    rate_above = len(dd.accepted) / above if above else 0.0
    rate_band = len(dd.band_accepted) / band if band else 0.0
    verdict = "looks fine"
    if above and rate_above < 0.5:
        verdict = "most candidates above it are rejected: consider raising it (costs only)"
    if band and rate_band > 0.3:
        verdict = "many merges found below it: consider lowering it"
    out += [
        "",
        f"DEDUPE_THRESHOLD (unchanged): {above} pairs ≥ threshold, "
        f"{len(dd.accepted)} accepted ({rate_above:.0%}).",
        f"- accepted: {_pct(dd.accepted)}",
        f"- rejected: {_pct(dd.rejected)}",
        f"- band 0.84–threshold sample: {len(dd.band_accepted)}/{band} accepted ({rate_band:.0%})",
        f"- verdict: {verdict}",
    ]
    return out


def _coverage(corpus: "Corpus", link_run: "LinkRun") -> list[str]:
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    unlinked: Counter[str] = Counter()
    for doc in corpus.docs:
        source = corpus.source[doc.content_id]
        demand_by_id = {d.id: d for d in doc.demands}
        for link in link_run.links.get(doc.content_id, []):
            d = demand_by_id[link.demand_id]
            if d.type not in EMBED_TYPES:
                continue
            counts[source][link.method] += 1
            counts["ALL"][link.method] += 1
            if link.method == "unlinked":
                unlinked[d.label] += 1
    out = _section("Linking coverage (concept and term demands)")
    out += [INFLATED_NOTE, ""]
    out += ["| source | total | alias | confirmed | unlinked |", "|---|---|---|---|---|"]
    for source in [*sorted(s for s in counts if s != "ALL"), "ALL"]:
        c = counts[source]
        n = sum(c.values()) or 1
        cells = [f"{c[m]} ({c[m] / n:.0%})" for m in ("alias", "confirmed", "unlinked")]
        out.append(f"| {source} | {sum(c.values())} | " + " | ".join(cells) + " |")
    out += ["", "15 most frequent unlinked labels:"]
    out += [f"- {label} — {n}" for label, n in unlinked.most_common(15)]
    return out


def _spot_check(
    corpus: "Corpus", graph: ConceptGraph, link_run: "LinkRun", rng: random.Random
) -> list[str]:
    linked: dict[str, list[tuple[Any, Link]]] = {"alias": [], "confirmed": []}
    for doc in corpus.docs:
        for link in link_run.links.get(doc.content_id, []):
            if link.method in linked:
                linked[link.method].append((doc, link))
    n_emb = min(len(linked["confirmed"]), 6)
    picks = rng.sample(linked["confirmed"], n_emb)
    picks += rng.sample(linked["alias"], min(10 - n_emb, len(linked["alias"])))
    out = _section("10 random entity links to spot-check")
    out.append("(6 model-confirmed links, the uncertain kind, and 4 exact-alias links)")
    for i, (doc, link) in enumerate(picks, 1):
        d = next(x for x in doc.demands if x.id == link.demand_id)
        para = next((p.text for p in doc.paragraphs if p.id == d.paragraph_id), "")
        sentence = sentence_around(para, d.anchor.exact, d.anchor.prefix)
        concept = graph.get(link.target_id)
        score = f", cos {link.score:.3f}" if link.score is not None else ""
        out.append(
            f'{i}. "{d.anchor.exact}" → **{concept.label}** ({link.method}{score})\n'
            f"   context: {sentence[:220]}"
        )
    return out


def _costs(corpus: "Corpus", cache: Any, ledger: list) -> list[str]:
    ingest = sum(c.cost_usd for d in corpus.docs for c in d.llm_calls)
    build_llm = cache.llm_cost_new + cache.llm_cost_cached
    total = ingest + build_llm + cache.embed_cost_new
    out = _section("LLM cost")
    out += [
        f"- ingestion (demand extraction, {len(corpus.docs)} docs): ${ingest:.3f}",
        f"- concept build LLM calls ({len(ledger)} calls; ${cache.llm_cost_new:.3f} this run, "
        f"${cache.llm_cost_cached:.3f} from cache): ${build_llm:.3f}",
        f"- embeddings this run: ${cache.embed_cost_new:.4f}",
        f"- **total: ${total:.3f}**",
    ]
    calls: Counter[str] = Counter(m.task for m in ledger)
    fell: Counter[str] = Counter(m.task for m in ledger if m.fell_back)
    out.append(
        "- calls by task (fallbacks): "
        + ", ".join(f"{t} {n} ({fell[t]})" for t, n in sorted(calls.items()))
    )
    return out
