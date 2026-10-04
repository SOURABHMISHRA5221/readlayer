"""Before/after section of the concept build report: what a rebuild changed (M2.1 onward)."""

import random
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

from app.graph import build
from app.graph.graph import ConceptGraph
from app.graph.linking import EMBED_TYPES, alias_target, sentence_around

if TYPE_CHECKING:
    from scripts.build_concepts import Corpus, LinkRun
    from scripts.build_report import BuildResult

METHODS = ("alias", "confirmed", "unlinked")
METHOD_NAMES = {"alias": "exact-name", "confirmed": "model", "unlinked": "unlinked"}


@dataclass
class Previous:
    graph: ConceptGraph | None
    graph_bytes: bytes | None
    links: dict[str, dict[str, str | None]]  # content_id -> demand id -> target id


def render_comparison(
    *,
    corpus: "Corpus",
    graph: ConceptGraph,
    result: "BuildResult | None",
    link_run: "LinkRun",
    prev: Previous,
    rng: random.Random,
) -> list[str]:
    out = ["", "## Before / after", ""]
    before_n = len(prev.graph) if prev.graph else 0
    out.append(f"Concepts: {before_n} → {len(graph)} ({len(graph) - before_n:+d})")
    out += _coverage_table(corpus, link_run, prev)
    out += _unlinked(corpus, graph, result, link_run)
    old_ids = {c.id for c in prev.graph.concepts} if prev.graph else set()
    out += _new_chains(graph, old_ids, rng)
    out += _new_links(corpus, graph, link_run, prev, old_ids, rng)
    return out


def _before_method(prev: Previous, content_id: str, demand: Any) -> str:
    target = prev.links.get(content_id, {}).get(demand.id)
    if target is None:
        return "unlinked"
    if prev.graph is not None and alias_target(prev.graph, demand) == target:
        return "alias"
    return "confirmed"


def _coverage_table(corpus: "Corpus", link_run: "LinkRun", prev: Previous) -> list[str]:
    before: Counter[str] = Counter()
    after: Counter[str] = Counter()
    for doc in corpus.docs:
        by_id = {d.id: d for d in doc.demands}
        for link in link_run.links.get(doc.content_id, []):
            d = by_id[link.demand_id]
            if d.type not in EMBED_TYPES:
                continue
            after[link.method] += 1
            before[_before_method(prev, doc.content_id, d)] += 1
    out = ["", "Linking coverage, concept and term demands in the corpus:", ""]
    out += ["| | total | " + " | ".join(METHOD_NAMES[m] for m in METHODS) + " |"]
    out += ["|---|---|---|---|---|"]
    for name, c in (("before", before), ("after", after)):
        n = sum(c.values()) or 1
        cells = [f"{c[m]} ({c[m] / n:.0%})" for m in METHODS]
        out.append(f"| {name} | {sum(c.values())} | " + " | ".join(cells) + " |")
    return out


def _cosine(a: Any, b: Any) -> float:
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b) or 1.0))


def classify_unlinked(
    label: str,
    graph: ConceptGraph,
    fates: dict[str, str],
    label_vecs: dict[str, list[float]],
    floor: float,
) -> str:
    fate = fates.get(build.normalize_label(label))
    if fate is None:
        return "not a candidate"
    if not fate.startswith("kept as "):
        return fate
    concept = graph.get(fate.removeprefix("kept as "))
    vec, cvec = label_vecs.get(label), graph.vector(concept.id) if concept else None
    if concept is None or vec is None or cvec is None:
        return fate
    cos = _cosine(vec, cvec)
    if cos < floor:
        return f"in graph as {concept.label}, label cosine {cos:.3f} below floor {floor}"
    return f"in graph as {concept.label} (cos {cos:.3f}); model chose none or not in top 5"


def _unlinked(
    corpus: "Corpus", graph: ConceptGraph, result: "BuildResult | None", link_run: "LinkRun"
) -> list[str]:
    counts: Counter[str] = Counter()
    for doc in corpus.docs:
        by_id = {d.id: d for d in doc.demands}
        for link in link_run.links.get(doc.content_id, []):
            d = by_id[link.demand_id]
            if d.type in EMBED_TYPES and link.method == "unlinked":
                counts[d.label] += 1
    fates = result.fates if result else {}
    out = ["", "15 most frequent still-unlinked labels (classification):", ""]
    for label, n in counts.most_common(15):
        why = classify_unlinked(label, graph, fates, link_run.label_vecs, link_run.threshold)
        out.append(f"- {label} — {n}: {why}")
    return out


def _new_chains(graph: ConceptGraph, old_ids: set[str], rng: random.Random) -> list[str]:
    new = [c for c in graph.concepts if c.id not in old_ids and c.prerequisites]
    deep = [c for c in new if len(graph.prerequisite_chain(c.id)) >= 3]
    pool = deep if len(deep) >= 10 else new
    out = ["", "10 sample prerequisite chains ending in a new concept (most basic first):", ""]
    for c in rng.sample(pool, min(10, len(pool))):
        out.append("- " + " → ".join(x.label for x in graph.prerequisite_chain(c.id)))
    return out


def _new_links(
    corpus: "Corpus",
    graph: ConceptGraph,
    link_run: "LinkRun",
    prev: Previous,
    old_ids: set[str],
    rng: random.Random,
) -> list[str]:
    fresh = []
    for doc in corpus.docs:
        before = prev.links.get(doc.content_id, {})
        for link in link_run.links.get(doc.content_id, []):
            if link.target_id is not None and link.target_id != before.get(link.demand_id):
                fresh.append((doc, link))
    out = [
        "",
        f"10 random new links to spot-check (of {len(fresh)} links that are new or changed):",
        "",
    ]
    for i, (doc, link) in enumerate(rng.sample(fresh, min(10, len(fresh))), 1):
        d = next(x for x in doc.demands if x.id == link.demand_id)
        para = next((p.text for p in doc.paragraphs if p.id == d.paragraph_id), "")
        concept = graph.get(link.target_id)
        tag = "new concept" if link.target_id not in old_ids else "existing concept"
        score = f", cos {link.score:.3f}" if link.score is not None else ""
        out.append(
            f'{i}. "{d.anchor.exact}" → **{concept.label}** '
            f"({METHOD_NAMES[link.method]}{score}; {tag})\n"
            f"   context: {sentence_around(para, d.anchor.exact, d.anchor.prefix)[:220]}"
        )
    return out
