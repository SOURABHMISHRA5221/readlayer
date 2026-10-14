"""Online concept growth, pure parts (M2.2 plan §C.2, DESIGN §2). No I/O, no SDK.

When a new article has concept/term demands that link to nothing, growth proposes concepts for
them. This module picks the demands, decides what counts as a verified concept, builds the
Concept and keeps its prerequisites to existing concepts only, so the graph stays acyclic. The
calls and the store live in app/graph/grow.py.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import networkx as nx

from app.graph.build import KEEP_KINDS, SINGLE_DOC_MIN_SPEC, Prereq, difficulty, normalize_label
from app.graph.enrich import ConceptInfo
from app.graph.graph import ConceptGraph
from app.graph.growth_need import untried_groups
from app.graph.linking import phrase, sentence_around
from app.graph.models import DOMAINS, Concept
from app.ingest.models import Demand

# Kinds whose concepts never absorb a differently-labelled candidate (mirrors never_merge_kind
# in data/graph_overrides.yaml, which isn't shipped with the API; a test keeps them equal).
NEVER_MERGE_KINDS = frozenset({"institution", "regulator", "committee", "index", "index_provider"})
PREREQ_NEAREST = 20
PREREQ_BASICS = 20
# A single everyday English word ("Health", "Level", "Room") can't carry a glossary-only sense:
# exact-match linking would attach that sense to every ordinary use of the word. Seeds and grown
# concepts must be multi-word or rarer than this (wordfreq Zipf scale; M2.2 seeding dry run).
EVERYDAY_ZIPF = 4.5


def everyday_word(label: str, zipf: float) -> bool:
    return " " not in label.strip() and zipf >= EVERYDAY_ZIPF


@dataclass(frozen=True)
class GrowthPick:
    label: str
    sentence: str
    salience: float
    demand_ids: tuple[str, ...]  # every demand in the article with this label
    phrase: str = ""  # the mention as the linker shows it: "exact (label)"
    merged_labels: tuple[str, ...] = ()  # same-page picks merged into this one (M9 part 2)


def pick(
    demands: Sequence[Demand],
    paragraphs: dict[str, str],
    limit: int,
    exclude: frozenset[str] = frozenset(),
) -> list[GrowthPick]:
    """Unlinked concept/term demands, one per normalised label, most salient first; labels in
    `exclude` (already tried on this page, M9) are skipped."""
    groups = untried_groups(demands, exclude)
    picks = []
    for members in groups.values():
        top = max(members, key=lambda d: (d.salience, d.id))
        para = paragraphs.get(top.paragraph_id, "")
        picks.append(
            GrowthPick(
                top.label,
                sentence_around(para, top.anchor.exact, top.anchor.prefix),
                top.salience,
                tuple(d.id for d in members),
                phrase(top),
            )
        )
    picks.sort(key=lambda p: (-p.salience, p.label))
    return picks[: max(0, limit)]


def merge_refused(existing: Concept, label: str) -> bool:
    """A named organisation never absorbs a differently-labelled candidate."""
    if existing.kind not in NEVER_MERGE_KINDS:
        return False
    names = {normalize_label(x) for x in [existing.label, *existing.aliases]}
    return normalize_label(label) not in names


def verified(info: ConceptInfo, label: str = "", zipf: float = 0.0) -> bool:
    """A verified concept (plan §C.2): a taxonomy domain, a kept kind, specialised enough to be
    worth a concept from a single article, and not a single everyday word. The schema already
    guarantees the shape."""
    return (
        info.domain in DOMAINS
        and info.kind in KEEP_KINDS
        and info.specialization >= SINGLE_DOC_MIN_SPEC
        and not everyday_word(label, zipf)
    )


def unique_id(slug: str, taken: set[str]) -> str:
    cid, n = slug, 2
    while cid in taken:
        cid, n = f"{slug}_{n}", n + 1
    return cid


def make_concept(
    cid: str, label: str, info: ConceptInfo, zipf: float, vector: Sequence[float]
) -> Concept:
    return Concept(
        id=cid,
        label=label,
        domain=info.domain,
        definition=info.definition,
        base_difficulty=difficulty(info.specialization, zipf),
        kind=info.kind,
        jurisdiction=info.jurisdiction,
        embedding=[round(float(x), 4) for x in vector],
    )


def prereq_pool(graph: ConceptGraph, vector: Sequence[float], domain: str) -> list[Concept]:
    """The 20 nearest concepts by label plus the 20 most basic of the same domain."""
    near = [c for c, _ in graph.nearest(list(vector), PREREQ_NEAREST)]
    basics = sorted(
        (c for c in graph.concepts if c.domain == domain),
        key=lambda c: (c.base_difficulty, c.id),
    )[:PREREQ_BASICS]
    return list({c.id: c for c in [*near, *basics]}.values())


def keep_prereqs(graph: ConceptGraph, new: Concept, picks: Sequence[Prereq]) -> list[str]:
    """At most 3 existing ids, best confidence first; any edge that would close a cycle is
    dropped (impossible while prerequisites are existing concepts, checked anyway)."""
    ordered = sorted(
        (p for p in picks if graph.get(p.id) is not None and p.id != new.id),
        key=lambda p: (-p.confidence, p.id),
    )
    dag = nx.DiGraph((pre.id, c.id) for c in graph.concepts for pre in graph.prerequisites(c.id))
    kept: list[str] = []
    for p in ordered:
        if len(kept) == 3 or p.id in kept:
            continue
        dag.add_edge(p.id, new.id)
        if nx.is_directed_acyclic_graph(dag):
            kept.append(p.id)
        else:
            dag.remove_edge(p.id, new.id)
    return kept
