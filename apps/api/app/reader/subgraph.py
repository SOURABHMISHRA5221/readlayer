"""Knowledge map subgraph for one domain (DESIGN §15.1 item 3, §15.2). Pure.

At most 60 nodes: the reader's most relevant concepts in the domain (evidence count × recency
decay, ≤ 40), or for a reader with no evidence there yet the domain's most frequent concepts;
then their prerequisite closure, nearest prerequisites first, cut at 60. Edges only join nodes
in the set, so the result is a sub-DAG of the (acyclic) concept graph.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime

from app.graph.build import normalize_label
from app.graph.graph import ConceptGraph
from app.graph.models import Concept
from app.reader.model import Band, Edge

MAX_NODES = 60
MAX_RELEVANT = 40
NEW_READER_SEEDS = 20
MAX_MATCHES = 10
RECENCY_HALF_LIFE_DAYS = 30.0
RECENT = 3  # evidence items shown on a node card


@dataclass(frozen=True)
class Node:
    id: str
    label: str
    domain: str
    band: Band
    evidence_count: int
    last_seen: datetime | None
    depth: int
    # The last evidence items, newest first, for the node card (DESIGN §15.1 item 3).
    recent: tuple[tuple[str, datetime], ...] = ()


@dataclass(frozen=True)
class Subgraph:
    nodes: list[Node]
    edges: list[tuple[str, str]]  # (prerequisite, concept)
    truncated: bool


def relevance(edge: Edge, now: datetime) -> float:
    days = max(0.0, (now - edge.last_seen).total_seconds() / 86400)
    return len(edge.evidence) * 0.5 ** (days / RECENCY_HALF_LIFE_DAYS)


def search(graph: ConceptGraph, q: str, domain: str | None) -> list[Concept]:
    needle = normalize_label(q)
    if not needle:
        return []
    hits = []
    for c in graph.concepts:
        if domain and c.domain != domain:
            continue
        names = [normalize_label(c.label), *(normalize_label(a) for a in c.aliases)]
        if any(needle in n for n in names):
            starts = any(n.startswith(needle) for n in names)
            hits.append((not starts, -c.doc_freq, c.label.casefold(), c))
    return [h[-1] for h in sorted(hits, key=lambda h: h[:3])[:MAX_MATCHES]]


def seeds(graph: ConceptGraph, knows: Mapping[str, Edge], domain: str, now: datetime) -> list[str]:
    ranked = sorted(
        (
            (-relevance(e, now), cid)
            for cid, e in knows.items()
            if (c := graph.get(cid)) is not None and c.domain == domain and e.evidence
        ),
    )
    if ranked:
        return [cid for _, cid in ranked[:MAX_RELEVANT]]
    common = sorted(
        (c for c in graph.concepts if c.domain == domain), key=lambda c: (-c.doc_freq, c.id)
    )
    return [c.id for c in common[:NEW_READER_SEEDS]]


def closure(
    graph: ConceptGraph, start: list[str], limit: int = MAX_NODES
) -> tuple[list[str], bool]:
    """Start nodes plus prerequisites, breadth-first by hop distance, cut at `limit`."""
    kept: list[str] = []
    seen: set[str] = set()
    frontier = [cid for cid in start if graph.get(cid) is not None]
    while frontier:
        level = []
        for cid in frontier:
            if cid not in seen:
                seen.add(cid)
                level.append(cid)
        room = limit - len(kept)
        if len(level) > room:
            kept.extend(level[:room])
            return kept, True
        kept.extend(level)
        frontier = sorted(
            {p.id for cid in level for p in graph.prerequisites(cid) if p.id not in seen}
        )
    return kept, False


def knowledge_subgraph(
    graph: ConceptGraph,
    knows: Mapping[str, Edge],
    band_of_concept: Callable[[Concept], Band],
    now: datetime,
    domain: str | None = None,
    q: str = "",
) -> Subgraph:
    if q.strip():
        start = [c.id for c in search(graph, q, domain)]
    elif domain:
        start = seeds(graph, knows, domain, now)
    else:
        start = []
    ids, truncated = closure(graph, start)
    members = set(ids)
    edges = sorted((p.id, cid) for cid in ids for p in graph.prerequisites(cid) if p.id in members)
    depth = _depths(ids, edges)
    nodes = []
    for cid in ids:
        c = graph.get(cid)
        assert c is not None
        e = knows.get(cid)
        nodes.append(
            Node(
                id=cid,
                label=c.label,
                domain=c.domain,
                band=band_of_concept(c),
                evidence_count=len(e.evidence) if e else 0,
                last_seen=e.last_seen if e else None,
                depth=depth[cid],
                recent=tuple((ev.type, ev.at) for ev in reversed(e.evidence[-RECENT:]))
                if e
                else (),
            )
        )
    return Subgraph(nodes, edges, truncated)


def _depths(ids: list[str], edges: list[tuple[str, str]]) -> dict[str, int]:
    """Longest path from a root of the subgraph: foundations 0, advanced below."""
    parents: dict[str, list[str]] = {cid: [] for cid in ids}
    for p, c in edges:
        parents[c].append(p)
    depth: dict[str, int] = {}

    def visit(cid: str) -> int:
        if cid not in depth:
            depth[cid] = 1 + max((visit(p) for p in parents[cid]), default=-1)
        return depth[cid]

    for cid in ids:
        visit(cid)
    return depth
