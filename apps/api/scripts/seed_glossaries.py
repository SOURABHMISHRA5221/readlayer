"""Seed the taxonomy domains from Wikipedia glossaries (M2.2 plan §B, decision 34).

    cd apps/api && uv run python -m scripts.seed_glossaries --project   # cost check, no LLM
    cd apps/api && uv run python -m scripts.seed_glossaries --dry-run   # build, write locally

Reads data/concepts.json (the current graph) and data/glossaries.yaml. Pages come only through
safe_fetch (robots honoured, 1 request/s) and are cached under data/build_cache/glossary/. The
pipeline: parse (app/graph/glossary.py) → drop exact matches of existing labels/aliases → rank
each domain by word frequency, keep SEED_PER_DOMAIN → dedupe against the graph and among the
candidates (embeddings ≥ DEDUPE_THRESHOLD, then link_merge; named organisations never absorb a
differently-labelled candidate) → concept_define v3 → keep rule (kept kinds; glossary seeds are
exempt from the single-doc rule) → prerequisites from the 20 nearest plus the 20 most basic
concepts of the same domain (≤ 3, cycles broken, DAG asserted) → kind and jurisdiction for
existing concepts (concept_jurisdiction) → the graph overrides.

Writes data/concepts.seeded.json (gitignored) and evals/seed_report.md (counts only, no glossary
text). Never writes Cloud Storage, Firestore or content docs; the upload happens later, after
Sourabh's yes on these numbers. Glossary snippets stay in the build cache.
"""

import argparse
import asyncio
import math
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

import networkx as nx
import numpy as np
import yaml
from wordfreq import zipf_frequency

from app.config import get_settings
from app.graph import build, enrich
from app.graph.glossary import parse
from app.graph.graph import ConceptGraph
from app.graph.models import Concept, ConceptGraphFile
from app.graph.overrides import Overrides, patch_adds, patch_remove_aliases, pending_adds
from app.ingest.safe_fetch import FetchError, SafeFetcher
from app.ingest.urls import normalize_url
from app.log import configure_logging
from scripts.apply_overrides import unique_id
from scripts.build_cache import BuildCache
from scripts.build_concepts import (
    CACHE_DIR,
    CONCEPTS_FILE,
    DATA_DIR,
    OVERRIDES_FILE,
    corpus_sources,
    heldout_urls,
)

SEED_PER_DOMAIN = 300
MERGE_TOP_K = 3  # nearest other candidates each candidate is compared with
GLOSSARY_FILE = DATA_DIR / "glossaries.yaml"
HTML_DIR = CACHE_DIR / "glossary"
SEEDED_FILE = DATA_DIR / "concepts.seeded.json"
REPORT_FILE = Path(__file__).parents[1] / "evals" / "seed_report.md"
FETCH_INTERVAL_S = 1.0
PREREQ_NEAREST = 20
PREREQ_BASICS = 20
PROJECTION_LIMIT_USD = 4.0
EST_CALL_USD = 0.002  # per batched MODEL_FAST call when the cache has no history for a task


@dataclass
class Candidate:
    label: str
    aliases: list[str]
    snippet: str
    domain_hint: str
    source: str
    zipf: float = 0.0
    merged_labels: list[str] = field(default_factory=list)


@dataclass
class Counts:
    pages: int = 0
    parsed: int = 0
    exact_existing: int = 0
    duplicates: int = 0
    ranked_out: int = 0
    kept_for_define: int = 0
    merged_into_graph: int = 0
    merged_together: int = 0
    defined: int = 0
    dropped_kind: Counter[str] = field(default_factory=Counter)
    new: int = 0
    prereq_edges: int = 0


def wiki_url(title: str) -> str:
    return "https://en.wikipedia.org/wiki/" + quote(title, safe="(),_–")


async def fetch_pages(sources: dict[str, list[str]]) -> dict[str, bytes]:
    taken = set(corpus_sources()) | heldout_urls()
    HTML_DIR.mkdir(parents=True, exist_ok=True)
    fetcher, pages = SafeFetcher(), {}
    for titles in sources.values():
        for title in titles:
            url = wiki_url(title)
            if normalize_url(url) in taken:
                raise SystemExit(f"{title} is in the corpus or the held-out set")
            path = HTML_DIR / f"{title.replace('/', '_')}.html"
            if path.exists():
                pages[title] = path.read_bytes()
                continue
            try:
                page = await fetcher.fetch(url)
            except FetchError as exc:
                print(f"  skipped {title}: {exc.code}")
                continue
            path.write_bytes(page.body)
            pages[title] = page.body
            await asyncio.sleep(FETCH_INTERVAL_S)
    return pages


def collect(
    sources: dict[str, list[str]], pages: dict[str, bytes], graph: ConceptGraph
) -> tuple[dict[str, list[Candidate]], dict[str, Counts]]:
    counts: dict[str, Counts] = defaultdict(Counts)
    seen: set[str] = set()
    by_domain: dict[str, list[Candidate]] = defaultdict(list)
    for domain, titles in sources.items():
        for title in titles:
            if title not in pages:
                continue
            counts[domain].pages += 1
            for e in parse(pages[title]):
                counts[domain].parsed += 1
                key = build.normalize_label(e.label)
                if graph.lookup(e.label) is not None:
                    counts[domain].exact_existing += 1
                    continue
                if key in seen:
                    counts[domain].duplicates += 1
                    continue
                seen.add(key)
                by_domain[domain].append(
                    Candidate(
                        e.label,
                        list(e.aliases),
                        e.snippet,
                        domain,
                        title,
                        zipf_frequency(e.label, "en"),
                    )  # fmt: skip
                )
    ranked: dict[str, list[Candidate]] = {}
    for domain, cands in by_domain.items():
        cands.sort(key=lambda c: (-c.zipf, c.label))
        ranked[domain] = cands[:SEED_PER_DOMAIN]
        counts[domain].ranked_out = max(0, len(cands) - SEED_PER_DOMAIN)
        counts[domain].kept_for_define = len(ranked[domain])
    return ranked, counts


def _entry(c: Candidate) -> enrich.Entry:
    glossary = c.source.replace("_", " ")
    return enrich.Entry(
        c.label, tuple(c.aliases), (c.snippet, f"Listed in Wikipedia's {glossary}.")
    )


def merge_pairs(
    cands: list[Candidate], graph: ConceptGraph, vecs: np.ndarray, overrides: Overrides
) -> tuple[list[tuple[enrich.Entry, enrich.Entry]], list[tuple[str, int, int | str]]]:
    """Pairs for link_merge: each candidate vs its nearest graph concept, and vs at most its
    MERGE_TOP_K nearest other candidates (the build's rule), all ≥ DEDUPE_THRESHOLD. Comparing
    every pair above the threshold would ask ~12,000 pairs (glossary terms cluster)."""
    threshold = get_settings().dedupe_threshold
    norm = vecs / np.maximum(np.linalg.norm(vecs, axis=1, keepdims=True), 1e-9)
    pairs: list[tuple[enrich.Entry, enrich.Entry]] = []
    kinds: list[tuple[str, int, int | str]] = []  # ("graph", i, concept id) | ("cand", i, j)
    for i, c in enumerate(cands):
        concept, score = graph.nearest(vecs[i], 1)[0]
        if score >= threshold and not overrides.merge_refused(concept, c.label):
            pairs.append((_entry(c), enrich.Entry(concept.label, tuple(concept.aliases[:5]))))
            kinds.append(("graph", i, concept.id))
    sims = norm @ norm.T
    np.fill_diagonal(sims, -1.0)
    seen: set[tuple[int, int]] = set()
    for i in range(len(cands)):
        for j in np.argsort(-sims[i])[:MERGE_TOP_K]:
            j = int(j)
            key = (min(i, j), max(i, j))
            if sims[i, j] >= threshold and key not in seen:
                seen.add(key)
                pairs.append((_entry(cands[key[0]]), _entry(cands[key[1]])))
                kinds.append(("cand", key[0], key[1]))
    return pairs, kinds


async def dedupe(
    cands: list[Candidate],
    graph: ConceptGraph,
    cache: BuildCache,
    ledger: list,
    overrides: Overrides,
    counts: dict[str, Counts],
) -> list[Candidate]:
    vecs = np.asarray(await cache.embed([c.label for c in cands], "SEMANTIC_SIMILARITY"))
    pairs, kinds = merge_pairs(cands, graph, vecs, overrides)
    answers = await enrich.check_merges(pairs, cache.run, ledger)
    into_graph = {i for k, (kind, i, _) in enumerate(kinds) if kind == "graph" and answers.get(k)}
    same = [(i, j) for k, (kind, i, j) in enumerate(kinds) if kind == "cand" and answers.get(k)]
    joinable = [(i, j) for i, j in same if i not in into_graph and j not in into_graph]
    groups = build.clusters(len(cands), joinable)
    kept: list[Candidate] = []
    for group in groups:
        members = [cands[i] for i in group if i not in into_graph]
        if not members:
            continue
        head = max(members, key=lambda c: (c.zipf, -len(c.label)))
        for other in members:
            if other is not head:
                head.aliases.append(other.label)
                head.merged_labels.append(other.label)
                counts[head.domain_hint].merged_together += 1
        kept.append(head)
    for i in into_graph:
        counts[cands[i].domain_hint].merged_into_graph += 1
    return kept


async def define(
    cands: list[Candidate], cache: BuildCache, ledger: list, counts: dict[str, Counts]
) -> list[tuple[Candidate, enrich.ConceptInfo]]:
    infos = await enrich.define_concepts([_entry(c) for c in cands], cache.run, ledger)
    kept = []
    for i, c in enumerate(cands):
        info = infos.get(i)
        if info is None:
            continue
        counts[c.domain_hint].defined += 1
        if build.apply_keep(info.kind, is_seed=False, doc_groups=build.MIN_DOC_GROUPS):
            kept.append((c, info))
        else:
            counts[c.domain_hint].dropped_kind[info.kind] += 1
    return kept


def new_concepts(
    defined: list[tuple[Candidate, enrich.ConceptInfo]], graph: ConceptGraph, vecs: list
) -> list[Concept]:
    taken = {c.id for c in graph.concepts}
    out = []
    for (c, info), vec in zip(defined, vecs, strict=True):
        base = build.slug_ids([c.label])[0]
        cid, n = base, 2
        while cid in taken:
            cid, n = f"{base}_{n}", n + 1
        taken.add(cid)
        out.append(
            Concept(
                id=cid,
                label=c.label,
                aliases=sorted(set(c.aliases) - {c.label}),
                domain=info.domain,
                definition=info.definition,
                base_difficulty=build.difficulty(info.specialization, c.zipf),
                kind=info.kind,
                jurisdiction=info.jurisdiction,
                embedding=[round(float(x), 4) for x in vec],
            )
        )
    return out


async def add_prereqs(
    file: ConceptGraphFile, new_ids: set[str], cache: BuildCache, ledger: list
) -> tuple[ConceptGraphFile, int, list[tuple[str, str]]]:
    concepts = file.concepts
    texts = [f"{c.label} — {c.definition}" for c in concepts]
    vectors = np.asarray(await cache.embed(texts, "RETRIEVAL_DOCUMENT"))
    vectors = vectors / np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-9)
    by_domain: dict[str, list[int]] = defaultdict(list)
    for j, c in enumerate(concepts):
        by_domain[c.domain].append(j)
    basics = {
        d: sorted(js, key=lambda j: (concepts[j].base_difficulty, concepts[j].id))[:PREREQ_BASICS]
        for d, js in by_domain.items()
    }
    requests, order = [], []
    for i, c in enumerate(concepts):
        if c.id not in new_ids:
            continue
        sims = vectors @ vectors[i]
        sims[i] = -1.0
        near = [int(j) for j in np.argsort(-sims)[:PREREQ_NEAREST]]
        pool = [j for j in dict.fromkeys(near + basics[c.domain]) if j != i]
        requests.append(
            enrich.PrereqRequest(
                enrich.Entry(c.label, definition=c.definition),
                tuple((concepts[j].id, concepts[j].label) for j in pool),
            )
        )
        order.append(c.id)
    picks = await enrich.propose_prereqs(requests, cache.run, ledger)
    ids = {c.id for c in concepts}
    edges = {c.id: [build.Prereq(p, 1.0) for p in c.prerequisites] for c in concepts}
    for k, cid in enumerate(order):
        edges[cid] = build.validate_prereqs(cid, picks.get(k, []), ids)
    clean, removed = build.break_cycles(edges, {c.id: c.base_difficulty for c in concepts})
    assert nx.is_directed_acyclic_graph(build.prereq_digraph(clean))
    added = sum(len(clean[cid]) for cid in order)
    out = [c.model_copy(update={"prerequisites": [p.id for p in clean[c.id]]}) for c in concepts]
    return file.model_copy(update={"concepts": out}), added, removed


async def backfill_kinds(
    file: ConceptGraphFile, cache: BuildCache, ledger: list
) -> tuple[ConceptGraphFile, Counter[str]]:
    todo = [i for i, c in enumerate(file.concepts) if c.kind is None]
    entries = [
        enrich.Entry(file.concepts[i].label, definition=file.concepts[i].definition) for i in todo
    ]
    got = await enrich.classify_kind_jurisdiction(entries, cache.run, ledger)
    concepts = list(file.concepts)
    sources: Counter[str] = Counter()
    for k, i in enumerate(todo):
        if k in got:
            concepts[i] = concepts[i].model_copy(
                update={"kind": got[k].kind, "jurisdiction": got[k].jurisdiction}
            )
            sources["concept_jurisdiction"] += 1
        else:
            sources["still None"] += 1
    return file.model_copy(update={"concepts": concepts}), sources


def project(
    ranked: dict[str, list[Candidate]], graph: ConceptGraph, cache: BuildCache, n_pairs: int
) -> float:
    n = sum(len(v) for v in ranked.values())
    unknown_kind = sum(c.kind is None for c in graph.concepts)
    calls = {
        "link_merge": math.ceil(n_pairs / 20),
        "concept_define": math.ceil(n / 25),
        "concept_prereqs": math.ceil(n * 0.7 / 15),
        "concept_jurisdiction": math.ceil(unknown_kind / 50),
    }
    total = 0.0
    for task, k in calls.items():
        per = cache.cost_per_call(task) or EST_CALL_USD
        total += k * per
        print(f"  {task}: ~{k} calls × ${per:.4f}")
    total += n * 2 * 0.00002  # label + label—definition embeddings, generous
    print(f"projected spend ${total:.2f} for {n} candidates (limit ${PROJECTION_LIMIT_USD:.2f})")
    return total


def report(
    counts: dict[str, Counts],
    final: ConceptGraphFile,
    before: ConceptGraph,
    kind_sources: Counter[str],
    removed_cycles: list,
    size_mb: float,
    load_s: float,
    spend: float,
) -> str:
    new = [c for c in final.concepts if before.get(c.id) is None]
    per_domain_total = Counter(c.domain for c in final.concepts)
    per_domain_new = Counter(c.domain for c in new)
    lines = [
        "# Glossary seeding dry run (M2.2, decision 34)",
        "",
        f"{datetime.now(UTC).isoformat(timespec='seconds')} · from graph {before.version} "
        f"({len(before)} concepts) → {len(final.concepts)} concepts "
        f"({len(new)} new, overrides included). Nothing uploaded or written to Firestore.",
        "",
        "## Pipeline per glossary group (domain hint)",
        "",
        "| hint | pages | parsed | exact match (dropped) | duplicate | ranked out | to dedupe "
        "| merged into graph | merged together | defined | dropped by kind | new |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for hint, c in sorted(counts.items()):
        drop = ", ".join(f"{k} {v}" for k, v in c.dropped_kind.most_common(4)) or "0"
        lines.append(
            f"| {hint} | {c.pages} | {c.parsed} | {c.exact_existing} | {c.duplicates} "
            f"| {c.ranked_out} | {c.kept_for_define} | {c.merged_into_graph} "
            f"| {c.merged_together} | {c.defined} | {drop} | {c.new} |"
        )
    lines += [
        "",
        "## Concepts per taxonomy domain (final, as concept_define assigned them)",
        "",
        "| domain | total | new |",
        "|---|---|---|",
        *[f"| {d} | {per_domain_total[d]} | {per_domain_new[d]} |" for d in final.domains],
        "",
        f"- Kind and jurisdiction for pre-M2.2 concepts: {dict(kind_sources)}.",
        f"- Jurisdictions: {dict(Counter(c.jurisdiction for c in final.concepts).most_common(8))}.",
        f"- Prerequisite edges on new concepts: {sum(len(c.prerequisites) for c in new)}; "
        f"cycle edges removed: {len(removed_cycles)}.",
        f"- concepts.seeded.json {size_mb:.1f} MB; parse + graph build {load_s:.2f} s locally.",
        f"- New LLM and embedding spend for this run: ${spend:.3f}.",
        "",
        "## 20 random new concepts (definition, domain, kind, prerequisites)",
        "",
    ]
    rng = np.random.default_rng(7)
    by_id = {c.id: c for c in final.concepts}
    for c in [new[i] for i in rng.permutation(len(new))[:20]]:
        pre = ", ".join(by_id[p].label for p in c.prerequisites) or "none"
        lines.append(f"- **{c.label}** ({c.domain}, {c.kind}, {c.jurisdiction}): "
                     f"{c.definition} Prerequisites: {pre}.")  # fmt: skip
    return "\n".join(lines) + "\n"


async def main(args: argparse.Namespace) -> int:
    configure_logging("WARNING")
    settings = get_settings()
    cache = BuildCache(CACHE_DIR, settings)
    ledger: list = []
    raw = await asyncio.to_thread(CONCEPTS_FILE.read_bytes)
    base_file = ConceptGraphFile.model_validate_json(raw)
    graph = ConceptGraph(base_file)
    sources = yaml.safe_load(GLOSSARY_FILE.read_text(encoding="utf-8"))
    pages = await fetch_pages(sources)
    ranked, counts = collect(sources, pages, graph)
    print(f"{len(pages)} pages; {sum(len(v) for v in ranked.values())} candidates to dedupe")
    overrides = Overrides.load(OVERRIDES_FILE)
    cands = [c for v in ranked.values() for c in v]
    vecs = np.asarray(await cache.embed([c.label for c in cands], "SEMANTIC_SIMILARITY"))
    n_pairs = len(merge_pairs(cands, graph, vecs, overrides)[0])
    print(f"{n_pairs} link_merge pairs")
    projected = project(ranked, graph, cache, n_pairs)
    if args.project:
        return 0 if projected <= PROJECTION_LIMIT_USD else 2
    if projected > PROJECTION_LIMIT_USD:
        print("refusing: projected spend above the limit")
        return 2

    kept = await dedupe(cands, graph, cache, ledger, overrides, counts)
    defined = await define(kept, cache, ledger, counts)
    vecs = await cache.embed([c.label for c, _ in defined], "SEMANTIC_SIMILARITY")
    new = new_concepts(defined, graph, vecs)
    for c, _ in defined:
        counts[c.domain_hint].new += 1
    file = ConceptGraphFile(
        version=f"{datetime.now(UTC).date().isoformat()}-seeded",
        concepts=[*base_file.concepts, *new],
    )
    file, kind_sources = await backfill_kinds(file, cache, ledger)
    file = patch_remove_aliases(file, overrides)
    adds = pending_adds(file, overrides)
    if adds:
        add_vecs = await cache.embed([a.label for a in adds], "SEMANTIC_SIMILARITY")
        vectors = {a.label: list(v) for a, v in zip(adds, add_vecs, strict=True)}
        file, _ = patch_adds(file, adds, vectors, lambda s: zipf_frequency(s, "en"), unique_id)
    new_ids = {c.id for c in file.concepts if graph.get(c.id) is None}
    file, edges, removed = await add_prereqs(file, new_ids, cache, ledger)
    missing = {c.id for c in graph.concepts} - {c.id for c in file.concepts}
    assert not missing, f"existing concept ids removed: {sorted(missing)[:5]}"

    data = file.model_dump_json()
    SEEDED_FILE.write_text(data, encoding="utf-8")
    started = time.perf_counter()
    loaded = ConceptGraph(ConceptGraphFile.model_validate_json(data))
    load_s = time.perf_counter() - started
    assert loaded.is_acyclic()
    spend = cache.llm_cost_new + cache.embed_cost_new
    text = report(counts, file, graph, kind_sources, removed, len(data) / 1e6, load_s, spend)
    REPORT_FILE.write_text(text, encoding="utf-8")
    print(text)
    print(f"wrote {SEEDED_FILE} (gitignored) and {REPORT_FILE}; prerequisite edges {edges}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--project", action="store_true", help="cost check only (no LLM)")
    mode.add_argument("--dry-run", action="store_true", help="build and write locally only")
    sys.exit(asyncio.run(main(parser.parse_args())))
