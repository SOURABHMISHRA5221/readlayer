"""Knowledge map overview across domains (Design pass A5, DESIGN §15.1). Pure: no I/O.

Only what we have evidence for (decision 69 A): a prior guess is never drawn. For each domain the
reader has evidence in or chose (interest ≥ 0.5), most interest first, up to MAX_SOLID **solid**
concepts (an edge whose current band, with forgetting, is ≥ heard of; by band then doc_freq) and
up to MAX_READY **ready to learn** rings (not known by evidence, at least one prerequisite and every
prerequisite known by evidence, in any domain; by doc_freq), where known means an edge with
p ≥ KNOWN_P. Solid takes precedence, so a node is never both. Domains with no nodes are dropped
before the MAX_DOMAINS cap; with no evidence at all the map is empty (the web says so). Edges are
prerequisite links among the nodes: within a domain, plus at most MAX_BRIDGES across domains.
`p_know` stays prior-based: the recap's bands (/v1/me/bands) and goals use it.
"""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime

from app.graph.graph import ConceptGraph
from app.graph.models import Concept
from app.graph.taxonomy import DOMAIN_IDS
from app.reader import model
from app.reader.model import BANDS, Band, Edge
from app.reader.profile import WEEK
from app.reader.state import ReaderState

MAX_DOMAINS = 6
MAX_SOLID = 12
MAX_READY = 4
MAX_BRIDGES = 6
MAX_NODES = 100
KNOWN_P = 0.5  # the same "known" as reading goals (DESIGN §18)
CHOSEN_INTEREST = 0.5
RECENT = 3


@dataclass(frozen=True)
class OverviewNode:
    id: str
    label: str
    domain: str
    band: Band
    ready: bool
    goal: bool
    weight: float  # doc_freq normalised within the domain, 0..1
    definition: str
    recent: tuple[tuple[str, datetime], ...]
    rose_this_week: bool


@dataclass(frozen=True)
class Overview:
    domains: tuple[str, ...]
    nodes: tuple[OverviewNode, ...]
    edges: tuple[tuple[str, str], ...]  # (prerequisite, concept)


def p_know(concept: Concept, state: ReaderState, now: datetime) -> float:
    p0 = model.prior(state.theta.get(concept.domain, 0.0), concept.base_difficulty)
    edge = state.edges.get(concept.id)
    return model.current_p_know(edge, p0, now) if edge else p0


def pick_domains(
    graph: ConceptGraph, state: ReaderState, interest: Mapping[str, float]
) -> tuple[str, ...]:
    """Candidates, most interest first; `build` drops the empty ones, then caps."""
    with_edges = {c.domain for cid in state.edges if (c := graph.get(cid)) is not None}
    chosen = {d for d, v in interest.items() if v >= CHOSEN_INTEREST}
    return tuple(sorted(
        (d for d in DOMAIN_IDS if d in with_edges | chosen),
        key=lambda d: (-interest.get(d, 0.0), DOMAIN_IDS.index(d)),
    ))  # fmt: skip


def _rose(edge: Edge | None, now: datetime) -> bool:
    return bool(
        edge is not None
        and edge.band_prev is not None
        and edge.band_changed_at is not None
        and now - edge.band_changed_at <= WEEK
        and BANDS.index(edge.band) > BANDS.index(edge.band_prev)
    )


def _is_ready(
    c: Concept, solid_ids: set[str], graph: ConceptGraph, known: Callable[[Concept], bool]
) -> bool:
    """Not known and not already solid, with at least one prerequisite, all of them known (by
    evidence, any domain)."""
    prereqs = graph.prerequisites(c.id)
    return c.id not in solid_ids and not known(c) and bool(prereqs) and all(map(known, prereqs))


def build(
    graph: ConceptGraph,
    state: ReaderState,
    interest: Mapping[str, float],
    goal_ids: Iterable[str],
    now: datetime,
) -> Overview:
    domains = pick_domains(graph, state, interest)
    goals = set(goal_ids)
    by_domain: dict[str, list[Concept]] = {d: [] for d in domains}
    for c in graph.concepts:
        if c.domain in by_domain:
            by_domain[c.domain].append(c)
    p_cache: dict[str, float] = {}

    def p(c: Concept) -> float:
        if c.id not in p_cache:
            p_cache[c.id] = p_know(c, state, now)
        return p_cache[c.id]

    def known(c: Concept) -> bool:
        return c.id in state.edges and p(c) >= KNOWN_P

    nodes: list[OverviewNode] = []
    kept: list[str] = []
    for d in domains:
        if len(kept) == MAX_DOMAINS:
            break
        concepts = by_domain[d]
        top_freq = max((c.doc_freq for c in concepts), default=0) or 1
        solid = sorted(
            (c for c in concepts if c.id in state.edges and model.band_of(p(c)) != "unaware"),
            key=lambda c: (-BANDS.index(model.band_of(p(c))), -c.doc_freq, c.id),
        )[:MAX_SOLID]
        solid_ids = {c.id for c in solid}

        ready = sorted(
            (c for c in concepts if _is_ready(c, solid_ids, graph, known)),
            key=lambda c: (-c.doc_freq, c.id),
        )
        if not solid and not ready:
            continue
        kept.append(d)
        for c, is_ring in [*((c, False) for c in solid), *((c, True) for c in ready[:MAX_READY])]:
            edge = state.edges.get(c.id)
            recent = tuple(
                (e.type, e.at) for e in sorted(edge.evidence, key=lambda e: e.at, reverse=True)
            )[:RECENT] if edge else ()  # fmt: skip
            nodes.append(
                OverviewNode(
                    id=c.id,
                    label=c.label,
                    domain=c.domain,
                    band=model.band_of(p(c)),
                    ready=is_ring,
                    goal=c.id in goals,
                    weight=round(c.doc_freq / top_freq, 3),
                    definition=c.definition,
                    recent=recent,
                    rose_this_week=_rose(edge, now),
                )  # fmt: skip
            )
    nodes = nodes[:MAX_NODES]
    ids = {n.id for n in nodes}
    domain_of = {n.id: n.domain for n in nodes}
    within: list[tuple[str, str]] = []
    bridges: list[tuple[str, str]] = []
    for n in nodes:
        for q in graph.prerequisites(n.id):
            if q.id not in ids:
                continue
            (within if domain_of[q.id] == n.domain else bridges).append((q.id, n.id))
    return Overview(tuple(kept), tuple(nodes), tuple(within + sorted(bridges)[:MAX_BRIDGES]))
