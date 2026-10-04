"""Apply data/graph_overrides.yaml to the built graph without a rebuild, re-link affected docs.

Run:  cd apps/api && uv run python -m scripts.apply_overrides [--upload]

Renames change a concept's label, id and label embedding (prerequisite references follow).
Splits strip the split's labels from the source concept and add a new concept: definition from
concept_define, prerequisites from concept_prereqs, cycles broken as in the build. Only docs
with a demand that pointed at a changed concept, or whose label is a split/rename label, are
re-linked. LLM and embedding calls go through the build cache.
"""

import argparse
import asyncio
import re
import sys

import networkx as nx
import numpy as np
from wordfreq import zipf_frequency

from app.config import get_settings
from app.graph import build, enrich
from app.graph.graph import ConceptGraph
from app.graph.linking import EMBED_TYPES, sentence_around
from app.graph.models import Concept, ConceptGraphFile
from app.graph.overrides import (
    Overrides,
    Split,
    add_concepts,
    patch_renames,
    patch_split_sources,
)
from app.ingest.models import ContentDoc
from app.log import configure_logging
from app.store.blob_repo import write_bytes
from scripts.build_cache import BuildCache
from scripts.build_concepts import (
    CACHE_DIR,
    CONCEPTS_FILE,
    GCS_URI,
    OVERRIDES_FILE,
    PREREQ_NEIGHBOURS,
    label_vectors,
    link_docs,
    load_docs,
)

ENV_EXAMPLE = CONCEPTS_FILE.parents[1] / "apps" / "api" / ".env.example"


def calibrated_floor() -> float:
    """LINK_THRESHOLD as last calibrated by build_concepts (it rewrites .env.example)."""
    match = re.search(r"(?m)^LINK_THRESHOLD=([0-9.]+)$", ENV_EXAMPLE.read_text())
    if not match:
        raise SystemExit("LINK_THRESHOLD not found in .env.example")
    return float(match.group(1))


def unique_id(label: str, taken: set[str]) -> str:
    base = build.slug_ids([label])[0]
    cid, n = base, 2
    while cid in taken:
        cid, n = f"{base}_{n}", n + 1
    return cid


def snippets_for(split: Split, docs: list[ContentDoc]) -> tuple[str, ...]:
    out = []
    for doc in docs:
        texts = {p.id: p.text for p in doc.paragraphs}
        for d in doc.demands:
            if build.normalize_label(d.label) in split.keys and len(out) < 2:
                para = texts.get(d.paragraph_id, "")
                out.append(sentence_around(para, d.anchor.exact, d.anchor.prefix))
    return tuple(out)


async def new_concept(
    split: Split,
    file: ConceptGraphFile,
    docs: list[ContentDoc],
    cache: BuildCache,
    ledger: list,
) -> Concept:
    entry = enrich.Entry(split.label, tuple(split.aliases), snippets_for(split, docs))
    infos = await enrich.define_concepts([entry], cache.run, ledger)
    if 0 not in infos:
        raise SystemExit(f"concept_define returned nothing for {split.label!r}")
    info = infos[0]
    taken = {c.id for c in file.concepts}
    cid = unique_id(split.label, taken)
    label_vec = (await cache.embed([split.label], "SEMANTIC_SIMILARITY"))[0]
    prereqs = await prereqs_for(cid, split.label, info.definition, file, cache, ledger)
    return Concept(
        id=cid,
        label=split.label,
        aliases=split.aliases,
        domain=info.domain,
        definition=info.definition,
        base_difficulty=build.difficulty(info.specialization, zipf_frequency(split.label, "en")),
        prerequisites=[p.id for p in prereqs],
        embedding=[round(float(x), 4) for x in label_vec],
    )


async def prereqs_for(
    cid: str, label: str, definition: str, file: ConceptGraphFile, cache: BuildCache, ledger: list
) -> list[build.Prereq]:
    """Same candidate pool as the build: nearest by label+definition, plus basic concepts."""
    concepts = file.concepts
    texts = [f"{c.label} — {c.definition}" for c in concepts] + [f"{label} — {definition}"]
    vectors = np.asarray(await cache.embed(texts, "RETRIEVAL_DOCUMENT"))
    sims = vectors[:-1] @ vectors[-1]
    near = [int(j) for j in np.argsort(-sims)][:PREREQ_NEIGHBOURS]
    basics = [int(j) for j in np.argsort(-sims) if concepts[j].base_difficulty <= 0][:20]
    pool = list(dict.fromkeys(near + basics))
    request = enrich.PrereqRequest(
        enrich.Entry(label, definition=definition),
        tuple((concepts[j].id, concepts[j].label) for j in pool),
    )
    picks = await enrich.propose_prereqs([request], cache.run, ledger)
    return build.validate_prereqs(cid, picks.get(0, []), {c.id for c in concepts})


async def relabel_embeddings(
    file: ConceptGraphFile, moved: dict[str, str], cache: BuildCache
) -> ConceptGraphFile:
    renamed = [c for c in file.concepts if c.id in moved.values()]
    if not renamed:
        return file
    vecs = await cache.embed([c.label for c in renamed], "SEMANTIC_SIMILARITY")
    new = {c.id: [round(float(x), 4) for x in v] for c, v in zip(renamed, vecs, strict=True)}
    return file.model_copy(
        update={
            "concepts": [
                c.model_copy(update={"embedding": new[c.id]}) if c.id in new else c
                for c in file.concepts
            ]
        }
    )


def break_cycles(file: ConceptGraphFile) -> tuple[ConceptGraphFile, list[tuple[str, str]]]:
    edges = {c.id: [build.Prereq(p, 1.0) for p in c.prerequisites] for c in file.concepts}
    clean, removed = build.break_cycles(edges, {c.id: c.base_difficulty for c in file.concepts})
    concepts = [
        c.model_copy(update={"prerequisites": [p.id for p in clean[c.id]]}) for c in file.concepts
    ]
    out = file.model_copy(update={"concepts": concepts})
    assert nx.is_directed_acyclic_graph(build.prereq_digraph(clean))
    return out, removed


def affected_docs(
    docs: list[ContentDoc], changed_ids: set[str], keys: set[str]
) -> list[ContentDoc]:
    return [
        doc
        for doc in docs
        if any(
            d.target_id in changed_ids or build.normalize_label(d.label) in keys
            for d in doc.demands
        )
    ]


async def main(args: argparse.Namespace) -> int:
    configure_logging("WARNING")
    cache = BuildCache(CACHE_DIR, get_settings())
    ledger: list = []
    overrides = Overrides.load(OVERRIDES_FILE)
    file = ConceptGraphFile.model_validate_json(CONCEPTS_FILE.read_bytes())
    before = len(file.concepts)
    docs = await load_docs()

    file, moved = patch_renames(file, overrides, unique_id)
    file = await relabel_embeddings(file, moved, cache)
    file, todo = patch_split_sources(file, overrides)
    added = [await new_concept(s, file, docs, cache, ledger) for s, _ in todo]
    file = add_concepts(file, added)
    file, removed = break_cycles(file)
    CONCEPTS_FILE.write_text(file.model_dump_json(), encoding="utf-8")

    graph = ConceptGraph(file)
    changed_ids = set(moved) | {src for _, src in todo if src}
    keys = {build.normalize_label(r.from_) for r in overrides.rename}
    keys |= {k for s in overrides.split for k in s.keys}
    targets = affected_docs(docs, changed_ids, keys)
    old = {doc.content_id: {d.id: d.target_id for d in doc.demands} for doc in targets}
    vecs = await label_vectors(targets, cache)
    links, changed, asked = await link_docs(
        graph, targets, vecs, calibrated_floor(), cache, ledger, write=True
    )

    print(f"concepts: {before} → {len(file.concepts)}")
    print(f"renamed (old id → new id): {moved or 'none'}")
    for c in added:
        prereqs = ", ".join(graph.get(p).label for p in c.prerequisites) or "none"
        print(f"added {c.id}: {c.definition}\n  aliases: {c.aliases}; prerequisites: {prereqs}")
    print(f"cycle edges removed: {removed or 'none'}")
    print(f"re-linked {len(targets)} affected docs ({changed} changed, {asked} model questions)")
    by_id = {doc.content_id: {d.id: d for d in doc.demands} for doc in targets}
    for cid, doc_links in links.items():
        for link in doc_links:
            d = by_id[cid][link.demand_id]
            was = old[cid][link.demand_id]
            if d.type in EMBED_TYPES and (was != link.target_id) and (was or link.target_id):
                now = graph.get(link.target_id).label if link.target_id else "unlinked"
                print(f'  "{d.anchor.exact}": {was or "unlinked"} → {now} ({link.method})')
    cost = cache.llm_cost_new + cache.embed_cost_new
    print(f"cost this run: ${cost:.4f} ({len(ledger)} LLM calls)")
    if args.upload:
        await write_bytes(GCS_URI, CONCEPTS_FILE.read_bytes())
        print(f"uploaded {GCS_URI} (previous M2 graph stays at concepts.prev.json)")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--upload", action="store_true", help=f"upload to {GCS_URI}")
    sys.exit(asyncio.run(main(parser.parse_args())))
