"""M2: build the global concept graph from the ingested corpus (DESIGN §2), re-link demands.

Run:  cd apps/api && uv run python -m scripts.build_concepts [--upload] [--relink-only]

Steps: near-duplicate docs → concept candidates (doc_freq counts each duplicate group once) →
label embeddings → dedupe (cosine ≥ DEDUPE_THRESHOLD + LLM merge check) → definitions, kind and
difficulty (keep rule) → Wikidata ids (seeds from Wikipedia pages; others best-effort) → final
embeddings → prerequisites (≤ 3, DAG) → concepts.json → LINK_THRESHOLD calibration → re-link
every content doc → report. LLM and embedding results are cached under data/build_cache/.
"""

import argparse
import asyncio
import json
import math
import random
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import networkx as nx
import numpy as np
from wordfreq import zipf_frequency

from app.config import get_settings
from app.graph import build, enrich
from app.graph.enrich import LinkQuestion
from app.graph.graph import ConceptGraph
from app.graph.linking import (
    CANDIDATES,
    EMBED_TYPES,
    Link,
    alias_target,
    finish_links,
    phrase,
    plan_links,
    sentence_around,
)
from app.graph.models import Concept, ConceptGraphFile
from app.ingest.models import ContentDoc, Demand
from app.ingest.safe_fetch import FetchError, SafeFetcher
from app.ingest.urls import normalize_url
from app.log import configure_logging
from app.store.blob_repo import write_bytes
from app.store.content_repo import get_content_store
from scripts import build_projection, build_report
from scripts.build_cache import BuildCache
from scripts.collect_corpus import QIDS_FILE, parse_wiki_page, wiki_url
from scripts.ingest_corpus import CORPUS_FILE, DATA_DIR, WIKI_SOURCE, parse_corpus

CONCEPTS_FILE = DATA_DIR / "concepts.json"
PREV_CONCEPTS_FILE = DATA_DIR / "concepts.prev.json"
PREV_LINKS_FILE = DATA_DIR / "links.prev.json"
CACHE_DIR = DATA_DIR / "build_cache"
GCS_URI = "gs://readlayer-sourabh-26-graph/concepts.json"
GCS_PREV_URI = "gs://readlayer-sourabh-26-graph/concepts.prev.json"
PROJECTION_LIMIT_USD = 8.0

MERGE_TOP_K = 5
BAND_LOW, BAND_SAMPLE = 0.84, 40
PREREQ_NEIGHBOURS, PREREQ_BASICS = 20, 20
CANDIDATE_RECALL = 0.95
EVAL_SAMPLE = 150
WIKI_RATE_S = 1.0
WIKI_BUDGET_S = 600.0  # overridable with --wiki-budget
SEED = 7

_SHORT_DESC = re.compile(r'<div class="shortdescription[^"]*"[^>]*>([^<]+)</div>')
_ACRONYM = re.compile(r"[A-Z][A-Z0-9&]{1,7}")


# ---------------------------------------------------------------- corpus


@dataclass
class Corpus:
    docs: list[ContentDoc]
    source: dict[str, str]  # content_id -> source tag
    group: dict[str, int]  # content_id -> near-duplicate group
    dup_pairs: list[build.DuplicatePair]

    def is_news(self, content_id: str) -> bool:
        return self.source.get(content_id) != WIKI_SOURCE


async def load_docs() -> list[ContentDoc]:
    return [d async for d in get_content_store().iter_all()]


def corpus_sources() -> dict[str, str]:
    entries = parse_corpus(CORPUS_FILE.read_text(encoding="utf-8").splitlines())
    return {normalize_url(e.url): e.source for e in entries}


async def find_duplicates(docs: list[ContentDoc], cache: BuildCache) -> build_report.DupResult:
    lead = [f"{d.title}\n{d.paragraphs[0].text if d.paragraphs else ''}" for d in docs]
    vectors = np.asarray(await cache.embed(lead, "SEMANTIC_SIMILARITY"))
    sets = [build.shingles(" ".join(p.text for p in d.paragraphs)) for d in docs]
    pairs = build.duplicate_pairs(sets, vectors)
    groups = build.clusters(len(docs), [(p.a, p.b) for p in pairs])
    return build_report.DupResult(groups, pairs)


# ---------------------------------------------------------------- candidates


@dataclass
class Candidate:
    key: str
    news_labels: Counter[str] = field(default_factory=Counter)
    labels: Counter[str] = field(default_factory=Counter)
    exacts: Counter[str] = field(default_factory=Counter)
    news_exacts: Counter[str] = field(default_factory=Counter)
    groups: set[int] = field(default_factory=set)
    snippets: list[str] = field(default_factory=list)
    seed_title: str | None = None
    seed_qid: str | None = None

    @property
    def display(self) -> str:
        for counter in (self.news_labels, self.labels):
            if counter:
                return counter.most_common(1)[0][0]
        return re.sub(r"\s*\([^)]*\)", "", self.seed_title or self.key).strip()


def collect_candidates(corpus: Corpus, seeds: dict[str, dict]) -> dict[str, Candidate]:
    cands: dict[str, Candidate] = {}
    for doc in corpus.docs:
        texts = {p.id: p.text for p in doc.paragraphs}
        for d in doc.demands:
            key = build.normalize_label(d.label)
            if not key or len(key) > 80:
                continue
            c = cands.setdefault(key, Candidate(key))
            c.labels[d.label] += 1
            if corpus.is_news(doc.content_id):
                c.news_labels[d.label] += 1
                c.news_exacts[d.anchor.exact] += 1
            c.exacts[d.anchor.exact] += 1
            c.groups.add(corpus.group[doc.content_id])
            if len(c.snippets) < 2:
                para = texts.get(d.paragraph_id, "")
                c.snippets.append(sentence_around(para, d.anchor.exact, d.anchor.prefix))
    for info in seeds.values():
        key = build.normalize_label(info["title"])
        c = cands.setdefault(key, Candidate(key))
        c.seed_title, c.seed_qid = info["title"], info["qid"]
    return {k: c for k, c in cands.items() if c.groups or c.seed_title}


# ---------------------------------------------------------------- dedupe


@dataclass
class Merged:
    members: list[Candidate]

    @property
    def is_seed(self) -> bool:
        return any(m.seed_title for m in self.members)

    @property
    def groups(self) -> set[int]:
        return set().union(*(m.groups for m in self.members))

    @property
    def label(self) -> str:
        """The most frequent surface form in news text ("repo rate", "GDP"), counting only
        complete names (text that normalises to one of the members' labels) and acronyms, never
        fragments like "yields". Falls back to the model's label, and to the Wikipedia title only
        when no article used the concept at all.
        """
        return (
            news_surface_form(self.members)
            or max(
                self.members,
                key=lambda m: (m.news_labels.total(), m.labels.total(), m.seed_title is None),
            ).display
        )

    @property
    def qid(self) -> str | None:
        return next((m.seed_qid for m in self.members if m.seed_qid), None)

    def aliases(self, limit: int = 12) -> list[str]:
        counts: Counter[str] = Counter()
        for m in self.members:
            counts.update(m.labels)
            counts.update(m.exacts)
            if m.seed_title:
                counts[m.seed_title] += 10**6  # Wikipedia title always kept as an alias
        own = build.normalize_label(self.label)
        seen, out = {own}, []
        for text, _ in counts.most_common():
            key = build.normalize_label(text)
            if key and key not in seen:
                seen.add(key)
                out.append(text)
        return out[:limit]

    def entry(self, definition: str = "") -> enrich.Entry:
        snippets = tuple(s for m in self.members for s in m.snippets)[:2]
        return enrich.Entry(self.label, tuple(self.aliases(6)), snippets, definition)


def news_surface_form(members: list[Candidate]) -> str | None:
    names = {build.normalize_label(label) for m in members for label in m.labels}
    by_key: dict[str, Counter[str]] = {}
    for m in members:
        for text, n in m.news_exacts.items():
            key = build.normalize_label(text)
            if key in names or _ACRONYM.fullmatch(text):
                by_key.setdefault(key, Counter())[text] += n
    if not by_key:
        return None
    forms = max(by_key.values(), key=lambda c: c.total())
    text = forms.most_common(1)[0][0]
    return text[0].upper() + text[1:] if text.islower() else text


@dataclass
class DedupeResult:
    merged: list[Merged]
    accepted: list[float]
    rejected: list[float]
    band_accepted: list[float]
    band_rejected: list[float]


async def dedupe(
    cands: list[Candidate], cache: BuildCache, threshold: float, ledger: list
) -> DedupeResult:
    vectors = np.asarray(await cache.embed([c.display for c in cands], "SEMANTIC_SIMILARITY"))
    pairs = build.candidate_pairs(vectors, threshold, top_k=MERGE_TOP_K)
    entries = [
        enrich.Entry(c.display, tuple(x for x in c.labels if x != c.display)[:4]) for c in cands
    ]
    decisions = await enrich.check_merges(
        [(entries[i], entries[j]) for i, j, _ in pairs], cache.run, ledger
    )
    accepted = [(i, j) for k, (i, j, _) in enumerate(pairs) if decisions.get(k)]
    band = build.candidate_pairs(vectors, BAND_LOW, high=threshold, top_k=MERGE_TOP_K)
    band = random.Random(SEED).sample(band, min(BAND_SAMPLE, len(band)))
    band_dec = await enrich.check_merges(
        [(entries[i], entries[j]) for i, j, _ in band], cache.run, ledger
    )
    groups = build.clusters(len(cands), accepted)
    return DedupeResult(
        merged=[Merged([cands[i] for i in g]) for g in groups],
        accepted=[s for k, (*_, s) in enumerate(pairs) if decisions.get(k)],
        rejected=[s for k, (*_, s) in enumerate(pairs) if not decisions.get(k)],
        band_accepted=[s for k, (*_, s) in enumerate(band) if band_dec.get(k)],
        band_rejected=[s for k, (*_, s) in enumerate(band) if not band_dec.get(k)],
    )


# ---------------------------------------------------------------- Wikidata (best effort)


async def fetch_wiki(fetcher: SafeFetcher, label: str, cache: BuildCache) -> dict | None:
    if (hit := cache.wiki_get(label)) is not None:
        return hit
    try:
        page = await fetcher.fetch(wiki_url(label))
        html = page.body.decode(page.encoding or "utf-8", errors="replace")
        parsed = parse_wiki_page(html)
        desc = _SHORT_DESC.search(html)
        value = (
            {"title": parsed.title, "qid": parsed.qid, "desc": desc.group(1) if desc else ""}
            if parsed and parsed.qid
            else {"miss": "no page"}
        )
    except FetchError as exc:
        value = {"miss": exc.code}
    cache.wiki_put(label, value)
    return value


async def wikidata_best_effort(
    concepts: list[tuple[str, Merged, enrich.ConceptInfo]],
    taken: set[str],
    cache: BuildCache,
    ledger: list,
    budget_s: float = WIKI_BUDGET_S,
) -> dict[str, str]:
    """concept id -> QID for non-seed concepts, most frequent first. ≤ 1 request/s, gives up
    after `budget_s`, skips any failure, never raises.
    """
    found: list[tuple[str, enrich.WikiCandidate, str]] = []
    fetcher = SafeFetcher()
    started = time.monotonic()
    attempted = skipped = 0
    for cid, merged, info in concepts:
        if time.monotonic() - started > budget_s:
            print(f"wikidata: {budget_s:.0f}s budget reached after {attempted} lookups")
            break
        attempted += 1
        cached = cache.wiki_get(merged.label) is not None
        t0 = time.monotonic()
        try:
            page = await fetch_wiki(fetcher, merged.label, cache)
        except Exception as exc:  # best effort: skip this concept, keep going
            skipped += 1
            print(f"wikidata: skipped {merged.label!r}: {type(exc).__name__}")
            page = None
        if page and page.get("qid") and page["qid"] not in taken:
            entry = merged.entry(info.definition)
            found.append(
                (cid, enrich.WikiCandidate(entry, page["title"], page["desc"]), page["qid"])
            )
        if not cached:
            await asyncio.sleep(max(0.0, WIKI_RATE_S - (time.monotonic() - t0)))
    print(f"wikidata: {attempted} lookups, {skipped} errors, {len(found)} pages to confirm")
    try:
        decisions = await enrich.confirm_wikipedia([c for _, c, _ in found], cache.run, ledger)
    except Exception as exc:  # never block the build on Wikidata
        print(f"wikidata confirmation failed, no new ids: {type(exc).__name__}: {exc}")
        return {}
    out: dict[str, str] = {}
    for k, (cid, _, qid) in enumerate(found):
        if decisions.get(k) and qid not in taken:
            taken.add(qid)
            out[cid] = qid
    return out


# ---------------------------------------------------------------- prerequisites


async def prerequisites(
    ids: list[str],
    labels: list[str],
    defs: list[str],
    diffs: list[float],
    freq: list[int],
    vectors: np.ndarray,
    cache: BuildCache,
    ledger: list,
) -> tuple[dict[str, list[build.Prereq]], list[tuple[str, str]]]:
    sims = vectors @ vectors.T
    basics = [i for i in sorted(range(len(ids)), key=lambda i: -freq[i]) if diffs[i] <= 0]
    requests = []
    for i in range(len(ids)):
        near = [int(j) for j in np.argsort(-sims[i]) if j != i][:PREREQ_NEIGHBOURS]
        pool = list(dict.fromkeys(near + [j for j in basics if j != i][:PREREQ_BASICS]))
        requests.append(
            enrich.PrereqRequest(
                enrich.Entry(labels[i], definition=defs[i]),
                tuple((ids[j], labels[j]) for j in pool),
            )
        )
    picks = await enrich.propose_prereqs(requests, cache.run, ledger)
    allowed = set(ids)
    edges = {
        ids[i]: build.validate_prereqs(ids[i], picks.get(i, []), allowed) for i in range(len(ids))
    }
    return build.break_cycles(edges, dict(zip(ids, diffs, strict=True)))


# ---------------------------------------------------------------- calibration and linking


@dataclass
class LinkRun:
    threshold: float  # candidate floor (label cosine), calibrated for 95% candidate recall
    positives: list[float]  # label cosine to the true concept, variant-name matches
    hard_negatives: list[float]  # best wrong concept for the same mentions
    topk_recall: float  # true concept among the top-k candidates above the floor
    eval_counts: Counter[str]  # model check on sampled variant matches: correct/wrong/none
    links: dict[str, list[Link]]  # content_id -> links
    changed_docs: int
    questions: int
    label_vecs: dict[str, list[float]]  # demand label -> embedding


async def label_vectors(docs: list[ContentDoc], cache: BuildCache) -> dict[str, list[float]]:
    labels = sorted({d.label for doc in docs for d in doc.demands if d.type in EMBED_TYPES})
    return dict(zip(labels, await cache.embed(labels, "SEMANTIC_SIMILARITY"), strict=True))


def variant_matches(
    graph: ConceptGraph, docs: list[ContentDoc]
) -> list[tuple[ContentDoc, Demand, str]]:
    """Exact-alias matches whose label differs from the concept's label ("Gross domestic
    product" -> GDP): known-correct links that embedding retrieval must actually find.
    """
    out = []
    for doc in docs:
        for d in doc.demands:
            target = alias_target(graph, d) if d.type in EMBED_TYPES else None
            if target and build.normalize_label(d.label) != build.normalize_label(
                graph.get(target).label
            ):
                out.append((doc, d, target))
    return out


async def calibrate_and_link(
    graph: ConceptGraph, docs: list[ContentDoc], cache: BuildCache, ledger: list, write: bool
) -> LinkRun:
    vecs = await label_vectors(docs, cache)
    concepts = graph.concepts
    matrix = np.asarray([graph.vector(c.id) for c in concepts])
    row = {c.id: i for i, c in enumerate(concepts)}

    variants = variant_matches(graph, docs)
    positives, hard = [], []
    for _, d, target in variants:
        sims = matrix @ np.asarray(vecs[d.label])
        positives.append(float(sims[row[target]]))
        sims[row[target]] = -1.0
        hard.append(float(sims.max()))
    floor = math.floor(float(np.percentile(positives, 100 * (1 - CANDIDATE_RECALL))) * 1000) / 1000

    def question(doc: ContentDoc, d: Demand) -> LinkQuestion:
        near = graph.nearest(vecs[d.label], CANDIDATES)
        para = next((p.text for p in doc.paragraphs if p.id == d.paragraph_id), "")
        return LinkQuestion(
            d.id,
            phrase(d),
            sentence_around(para, d.anchor.exact, d.anchor.prefix),
            tuple((c.id, c.label, c.definition, s) for c, s in near if s >= floor),
        )

    in_topk = [
        target in {cid for cid, *_ in question(doc, d).candidates} for doc, d, target in variants
    ]
    sample = random.Random(SEED).sample(variants, min(EVAL_SAMPLE, len(variants)))
    eval_qs = [question(doc, d) for doc, d, _ in sample]
    asked = [i for i, q in enumerate(eval_qs) if q.candidates]
    answers = await enrich.confirm_links([eval_qs[i] for i in asked], cache.run, ledger)
    picks = {asked[k]: v for k, v in answers.items()}
    counts: Counter[str] = Counter()
    for i, (_, _, target) in enumerate(sample):
        pick = picks.get(i)
        counts["none" if pick is None else "correct" if pick == target else "wrong"] += 1

    plans = {}
    for doc in docs:
        paragraphs = {p.id: p.text for p in doc.paragraphs}
        plans[doc.content_id] = plan_links(graph, doc.demands, vecs, paragraphs, floor)
    all_qs = [(cid, q) for cid, plan in plans.items() for q in plan.questions]
    flat = await enrich.confirm_links([q for _, q in all_qs], cache.run, ledger)
    per_doc: dict[str, dict[int, str | None]] = {}
    position: Counter[str] = Counter()
    for k, (cid, _) in enumerate(all_qs):
        per_doc.setdefault(cid, {})[position[cid]] = flat.get(k)
        position[cid] += 1

    links: dict[str, list[Link]] = {}
    changed = 0
    store = get_content_store()
    for doc in docs:
        doc_links = finish_links(
            doc.demands, plans[doc.content_id], per_doc.get(doc.content_id, {})
        )
        links[doc.content_id] = doc_links
        targets = {lk.demand_id: lk.target_id for lk in doc_links}
        if any(d.target_id != targets[d.id] for d in doc.demands):
            changed += 1
            if write:
                demands = [d.model_copy(update={"target_id": targets[d.id]}) for d in doc.demands]
                await store.put(doc.model_copy(update={"demands": demands}))
    return LinkRun(
        floor,
        positives,
        hard,
        sum(in_topk) / max(len(in_topk), 1),
        counts,
        links,
        changed,
        len(all_qs),
        vecs,
    )


def update_env_example(threshold: float) -> None:
    path = Path(__file__).resolve().parents[1] / ".env.example"
    text = re.sub(r"(?m)^LINK_THRESHOLD=.*$", f"LINK_THRESHOLD={threshold}", path.read_text())
    path.write_text(text)


# ---------------------------------------------------------------- main build


async def build_graph(
    corpus: Corpus, cache: BuildCache, ledger: list, wiki_budget: float
) -> build_report.BuildResult:
    settings = get_settings()
    seeds = json.loads(QIDS_FILE.read_text(encoding="utf-8"))
    cands = sorted(collect_candidates(corpus, seeds).values(), key=lambda c: -len(c.groups))
    single = sum(1 for c in cands if len(c.groups) < build.MIN_DOC_GROUPS and not c.seed_title)
    print(f"candidates: {len(cands)} ({single} single-doc, admitted only if specialized)")

    dd = await dedupe(cands, cache, settings.dedupe_threshold, ledger)
    merged = sorted(dd.merged, key=lambda m: -len(m.groups))
    print(f"after merge: {len(merged)} concepts")

    infos = await enrich.define_concepts([m.entry() for m in merged], cache.run, ledger)

    def keep(i: int, m: Merged) -> bool:
        info = infos[i]
        return build.apply_keep(info.kind, m.is_seed, len(m.groups), info.specialization)

    kept = [(m, infos[i]) for i, m in enumerate(merged) if i in infos and keep(i, m)]
    dropped: Counter[str] = Counter()
    for i, m in enumerate(merged):
        if i in infos and not keep(i, m):
            in_keep_kinds = infos[i].kind in build.KEEP_KINDS
            dropped["single-doc, specialization 1" if in_keep_kinds else infos[i].kind] += 1
    print(f"kept {len(kept)}; dropped {dict(dropped)}; undefined {len(merged) - len(infos)}")

    ids = build.slug_ids([m.label for m, _ in kept])
    fates = candidate_fates(
        merged, infos, {id(m): cid for (m, _), cid in zip(kept, ids, strict=True)}
    )
    qids = {cid: m.qid for cid, (m, _) in zip(ids, kept, strict=True) if m.qid}
    seed_qids = len(qids)
    non_seed = [(cid, m, info) for cid, (m, info) in zip(ids, kept, strict=True) if not m.qid]
    qids |= await wikidata_best_effort(non_seed, set(qids.values()), cache, ledger, wiki_budget)
    print(f"wikidata ids: {len(qids)} ({seed_qids} from seeds, {len(qids) - seed_qids} new)")

    labels = [m.label for m, _ in kept]
    label_vecs = await cache.embed(labels, "SEMANTIC_SIMILARITY")  # stored; used for linking
    defs = [info.definition for _, info in kept]
    diffs = [
        build.difficulty(info.specialization, zipf_frequency(m.label, "en")) for m, info in kept
    ]
    freq = [len(m.groups) for m, _ in kept]
    vectors = np.asarray(
        await cache.embed(
            [f"{label} — {d}" for label, d in zip(labels, defs, strict=True)], "RETRIEVAL_DOCUMENT"
        )
    )
    edges, removed = await prerequisites(ids, labels, defs, diffs, freq, vectors, cache, ledger)
    assert nx.is_directed_acyclic_graph(build.prereq_digraph(edges))

    concepts = [
        Concept(
            id=cid,
            label=m.label,
            aliases=m.aliases(),
            wikidata=qids.get(cid),
            domain=info.domain,
            definition=info.definition,
            base_difficulty=diffs[i],
            prerequisites=[p.id for p in edges[cid]],
            embedding=[round(float(x), 4) for x in label_vecs[i]],
        )
        for i, (cid, (m, info)) in enumerate(zip(ids, kept, strict=True))
    ]
    graph_file = ConceptGraphFile(version=datetime.now(UTC).date().isoformat(), concepts=concepts)
    return build_report.BuildResult(
        graph_file,
        dict(zip(ids, freq, strict=True)),
        dd,
        dict(dropped),
        removed,
        len(qids),
        fates,
    )


def candidate_fates(
    merged: list[Merged], infos: dict[int, enrich.ConceptInfo], kept_ids: dict[int, str]
) -> dict[str, str]:
    """Normalised candidate label -> what the build did with it (for the unlinked report)."""
    fates: dict[str, str] = {}
    for i, m in enumerate(merged):
        if (cid := kept_ids.get(id(m))) is not None:
            fate = f"kept as {cid}"
        elif i not in infos:
            fate = "undefined (model skipped it)"
        elif infos[i].kind in build.KEEP_KINDS:
            fate = (
                f"dropped: single doc, specialization {infos[i].specialization} "
                f"(kind {infos[i].kind})"
            )
        else:
            fate = f"dropped: kind {infos[i].kind}"
        for c in m.members:
            fates[c.key] = fate
    return fates


def snapshot_previous(docs: list[ContentDoc]) -> build_report.Previous:
    """Keep the graph and links this build replaces, for the before/after report and GCS.

    Written once: a rerun after a crash reuses the snapshot instead of mistaking a half-new
    state for the previous one. Delete both files to start a fresh comparison.
    """
    if not PREV_CONCEPTS_FILE.exists() and CONCEPTS_FILE.exists():
        PREV_CONCEPTS_FILE.write_bytes(CONCEPTS_FILE.read_bytes())
        print(f"saved previous graph to {PREV_CONCEPTS_FILE}")
    if not PREV_LINKS_FILE.exists():
        links = {doc.content_id: {d.id: d.target_id for d in doc.demands} for doc in docs}
        PREV_LINKS_FILE.write_text(json.dumps(links), encoding="utf-8")
        print(f"saved previous links to {PREV_LINKS_FILE}")
    graph_bytes = PREV_CONCEPTS_FILE.read_bytes() if PREV_CONCEPTS_FILE.exists() else None
    return build_report.Previous(
        graph=ConceptGraph(ConceptGraphFile.model_validate_json(graph_bytes))
        if graph_bytes
        else None,
        graph_bytes=graph_bytes,
        links=json.loads(PREV_LINKS_FILE.read_text(encoding="utf-8")),
    )


async def main(args: argparse.Namespace) -> int:
    configure_logging("WARNING")
    settings = get_settings()
    if not settings.model_embed:
        print("MODEL_EMBED is not set")
        return 1
    cache = BuildCache(CACHE_DIR, settings)
    ledger: list = []
    docs = await load_docs()
    sources = corpus_sources()
    corpus_docs = [d for d in docs if d.url in sources]
    print(f"{len(docs)} content docs, {len(corpus_docs)} from the corpus")
    dup = await find_duplicates(corpus_docs, cache)
    corpus = Corpus(
        corpus_docs,
        {d.content_id: sources[d.url] for d in corpus_docs},
        {corpus_docs[i].content_id: g for g, members in enumerate(dup.groups) for i in members},
        dup.pairs,
    )

    if args.project:
        current = ConceptGraph(ConceptGraphFile.model_validate_json(CONCEPTS_FILE.read_bytes()))
        seeds = json.loads(QIDS_FILE.read_text(encoding="utf-8"))
        cands = list(collect_candidates(corpus, seeds).values())
        projection = await build_projection.project(cands, docs, current, cache)
        print(projection.render())
        ok = projection.total <= PROJECTION_LIMIT_USD
        print(f"limit ${PROJECTION_LIMIT_USD:.2f}: {'OK' if ok else 'EXCEEDED — do not run'}")
        return 0 if ok else 2

    prev = snapshot_previous(docs)
    if args.relink_only:
        graph_file = ConceptGraphFile.model_validate_json(CONCEPTS_FILE.read_bytes())
        result = None
    else:
        result = await build_graph(corpus, cache, ledger, args.wiki_budget)
        graph_file = result.graph_file
        CONCEPTS_FILE.write_text(graph_file.model_dump_json(), encoding="utf-8")
        print(f"wrote {CONCEPTS_FILE} ({CONCEPTS_FILE.stat().st_size / 1e6:.1f} MB)")

    graph = ConceptGraph(graph_file)
    assert graph.is_acyclic()
    link_run = await calibrate_and_link(graph, docs, cache, ledger, write=True)
    update_env_example(link_run.threshold)
    if args.upload:
        if prev.graph_bytes is not None:
            await write_bytes(GCS_PREV_URI, prev.graph_bytes)
            print(f"uploaded previous graph to {GCS_PREV_URI}")
        await write_bytes(GCS_URI, CONCEPTS_FILE.read_bytes())
        print(f"uploaded {GCS_URI}")

    report = build_report.render(
        corpus=corpus,
        dup=dup,
        graph=graph,
        result=result,
        link_run=link_run,
        cache=cache,
        ledger=ledger,
        prev=prev,
    )
    (DATA_DIR / "m2_report.md").write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--upload", action="store_true", help=f"upload to {GCS_URI}")
    parser.add_argument(
        "--wiki-budget",
        type=float,
        default=WIKI_BUDGET_S,
        help="seconds allowed for Wikidata lookups",
    )
    parser.add_argument(
        "--project",
        action="store_true",
        help=f"project the build cost (no LLM calls); exit 2 above ${PROJECTION_LIMIT_USD:.0f}",
    )
    parser.add_argument(
        "--relink-only",
        action="store_true",
        help="reuse data/concepts.json; only calibrate and re-link",
    )
    sys.exit(asyncio.run(main(parser.parse_args())))
