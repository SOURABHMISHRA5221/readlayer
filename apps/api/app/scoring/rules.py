"""DESIGN §5 scoring rules: how likely this reader is to miss each demand. Pure, no I/O.

Concept: p_know from the reader's KNOWS edge (forgetting applied lazily), or the IRT prior
when there is no edge, capped one hop by the best-known prerequisite + 0.1.
Term: σ(1.2·(zipf − τ)), τ = 3.5 − 0.4·θ_domain. Context: 0.8 if the reader engaged with a
content mentioning the same entity in the last 30 days, else 0.2; when the reference is linked
to a graph concept the reader has an edge for, or whose prior is ≥ 0.8, at least that p_know.
"""

from collections.abc import Collection, Mapping
from datetime import datetime
from typing import Literal

from app.graph.build import normalize_label
from app.graph.graph import ConceptGraph
from app.graph.models import Concept
from app.ingest.models import Demand
from app.reader import model
from app.reader.state import Density, ReaderState, clamp_offset

PREREQ_SLACK = 0.1
EXPLAINED_IN_TEXT_FACTOR = 0.4
TERM_SLOPE = 1.2
TERM_TAU_BASE = 3.5
TERM_TAU_PER_THETA = 0.4
CONTEXT_P_ENGAGED = 0.8
CONTEXT_P_NEW = 0.2
CONTEXT_CONFIDENT_PRIOR = 0.8  # a prior-only p_know this high also counts for a reference
STRUCTURE_WEIGHT = 0.3

ThresholdKind = Literal["span", "paragraph", "preread"]
# DESIGN §5 thresholds before the per-reader threshold_offset.
THRESHOLDS: Mapping[Density, Mapping[ThresholdKind, float]] = {
    "minimal": {"span": 0.60, "paragraph": 0.85, "preread": 0.55},
    "balanced": {"span": 0.45, "paragraph": 0.75, "preread": 0.45},
    "guided": {"span": 0.30, "paragraph": 0.65, "preread": 0.35},
}

# threshold_offset adaptation (DESIGN §5): more confident readers see fewer annotations.
OFFSET_STEP: Mapping[str, float] = {
    "knew_this": 0.02,
    "annotation_dismissed": 0.02,
    "text_searched": -0.02,
    "slowdown": -0.02,  # on an unannotated paragraph; emitted once dwell medians exist (M6)
}


def threshold(density: Density, kind: ThresholdKind, offset: float) -> float:
    return THRESHOLDS[density][kind] + clamp_offset(offset)


def theta_of(state: ReaderState, domain: str | None) -> float:
    return state.theta.get(domain, 0.0) if domain else 0.0


def concept_p(concept: Concept, state: ReaderState, now: datetime) -> float:
    """p_know for one concept: the edge with forgetting, else the IRT prior. No prereq cap."""
    p0 = model.prior(theta_of(state, concept.domain), concept.base_difficulty)
    edge = state.edges.get(concept.id)
    return model.current_p_know(edge, p0, now) if edge else p0


def capped_concept_p(
    concept: Concept, graph: ConceptGraph, state: ReaderState, now: datetime
) -> float:
    p = concept_p(concept, state, now)
    prereqs = graph.prerequisites(concept.id)
    if prereqs:
        best = max(concept_p(q, state, now) for q in prereqs)
        p = min(p, best + PREREQ_SLACK)
    return p


def term_p(zipf: float, theta: float) -> float:
    tau = TERM_TAU_BASE - TERM_TAU_PER_THETA * theta
    return model.sigmoid(TERM_SLOPE * (zipf - tau))


def entity_key(demand: Demand) -> str:
    """What a context demand refers to: the linked concept, else its normalised label."""
    return demand.target_id or "label:" + normalize_label(demand.label)


def demand_p(
    demand: Demand,
    concept: Concept | None,
    graph: ConceptGraph,
    state: ReaderState,
    now: datetime,
    fallback_domain: str | None,
    engaged_entities: Collection[str],
) -> float | None:
    """p_know for one demand, or None when it can't be scored (an unlinked concept)."""
    domain = concept.domain if concept else fallback_domain
    if demand.type == "term":
        return term_p(demand.zipf, theta_of(state, domain))
    if demand.type == "context":
        p = CONTEXT_P_ENGAGED if entity_key(demand) in engaged_entities else CONTEXT_P_NEW
        if concept is None:
            return p
        # A reference to a graph concept the reader knows (the RBI, the Sensex) needs no gloss
        # either, but only on real evidence (an edge) or a confident prior: a generic prior
        # guess from estimated difficulty shouldn't hide a reference (DESIGN §6).
        known = capped_concept_p(concept, graph, state, now)
        if concept.id in state.edges or known >= CONTEXT_CONFIDENT_PRIOR:
            return max(p, known)
        return p
    if concept is None:
        return None
    return capped_concept_p(concept, graph, state, now)


def span_score(p: float, salience: float, explained_in_text: bool) -> float:
    miss = (1.0 - p) * (EXPLAINED_IN_TEXT_FACTOR if explained_in_text else 1.0)
    return miss * salience


def paragraph_score(span_scores: Collection[float], structure: float, theta: float) -> float:
    """Noisy-OR over the paragraph's spans plus a structure term, clipped to [0, 1]."""
    none_missed = 1.0
    for s in span_scores:
        none_missed *= 1.0 - s
    raw = 1.0 - none_missed + STRUCTURE_WEIGHT * structure * (1.0 - model.sigmoid(theta))
    return max(0.0, min(1.0, raw))


def next_offset(offset: float, event_types: Collection[str]) -> float:
    return clamp_offset(offset + sum(OFFSET_STEP.get(t, 0.0) for t in event_types))


def explicitly_known(state: ReaderState, concept_id: str) -> bool:
    """The reader's latest explicit word on the concept is "I know this" (knew_this or a
    "known" correction). Such concepts aren't annotated, whatever p_know says (DESIGN §6)."""
    edge = state.edges.get(concept_id)
    if edge is None:
        return False
    for ev in reversed(edge.evidence):
        if ev.type == "knew_this" or (ev.type == "correction" and ev.w > 0):
            return True
        if ev.type in ("correction", "explain_opened", "text_searched"):
            return False
    return False
