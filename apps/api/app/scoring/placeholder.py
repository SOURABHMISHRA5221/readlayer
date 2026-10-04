"""PLACEHOLDER scorer for the local M6 slice — replaced by the real scorer in M4.

Uses the DESIGN §5 formulas with prior-only p_know (no reader graph: no KNOWS edges, no
forgetting, no threshold_offset) and θ per domain from hard-coded demo personas, then the
DESIGN §6 span caps. Only demands linked to a graph concept are annotated, because the card
needs a label and definition. No paragraph markers, pre-read or uncertainty prompts.
Pure: no I/O, no SDK imports.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from app.graph.graph import ConceptGraph
from app.graph.models import Concept
from app.ingest.models import Anchor, ContentDoc, Demand

PersonaKey = Literal["newcomer", "trader", "policy_student"]
Density = Literal["minimal", "balanced", "guided"]


@dataclass(frozen=True)
class Persona:
    label: str
    # θ per domain on the logit scale. "software" is not a graph domain yet, so it affects
    # nothing; it is kept so the persona reads as written.
    theta: Mapping[str, float]


PERSONAS: Mapping[PersonaKey, Persona] = {
    "newcomer": Persona(
        "Newcomer (engineer)",
        {"economics": -1.2, "finance": -1.0, "business": -0.3, "policy": -0.5, "software": 1.5},
    ),
    "trader": Persona(
        "Markets trader",
        {"finance": 1.5, "business": 0.8, "economics": -0.3, "policy": -1.0},
    ),
    "policy_student": Persona(
        "Policy student",
        {"economics": 1.2, "policy": 1.5, "finance": -1.0, "business": -0.4},
    ),
}

# DESIGN §5 span thresholds per density dial.
DENSITY_THRESHOLDS: Mapping[Density, float] = {"minimal": 0.60, "balanced": 0.45, "guided": 0.30}

PREREQ_SLACK = 0.1
EXPLAINED_IN_TEXT_FACTOR = 0.4
CONTEXT_P_NO_HISTORY = 0.2  # no reader history in this slice, so never "engaged"
TERM_SLOPE = 1.2
TERM_TAU_BASE = 3.5
TERM_TAU_PER_THETA = 0.4
WORDS_PER_SPAN = 80
MAX_SPANS_PER_PARAGRAPH = 2


@dataclass(frozen=True)
class SpanAnnotation:
    demand_id: str
    paragraph_id: str
    anchor: Anchor
    concept_id: str
    label: str
    definition: str
    domain: str
    base_difficulty: float
    prerequisites: tuple[str, ...]
    p_know: float
    salience: float
    score: float


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def prior(theta: float, difficulty: float) -> float:
    """DESIGN §4 IRT prior: σ(θ_domain − b)."""
    return sigmoid(theta - difficulty)


def p_know(
    demand: Demand, concept: Concept, graph: ConceptGraph, theta: Mapping[str, float]
) -> float:
    th = theta.get(concept.domain, 0.0)
    if demand.type == "term":
        tau = TERM_TAU_BASE - TERM_TAU_PER_THETA * th
        return sigmoid(TERM_SLOPE * (demand.zipf - tau))
    if demand.type == "context":
        return CONTEXT_P_NO_HISTORY
    p = prior(th, concept.base_difficulty)
    prereqs = graph.prerequisites(concept.id)
    if prereqs:
        best = max(prior(theta.get(q.domain, 0.0), q.base_difficulty) for q in prereqs)
        p = min(p, best + PREREQ_SLACK)
    return p


def span_score(demand: Demand, p: float) -> float:
    miss = (1.0 - p) * (EXPLAINED_IN_TEXT_FACTOR if demand.explained_in_text else 1.0)
    return miss * demand.salience


def word_count(doc: ContentDoc) -> int:
    return sum(len(p.text.split()) for p in doc.paragraphs)


def annotate(
    doc: ContentDoc, graph: ConceptGraph, theta: Mapping[str, float], threshold: float
) -> list[SpanAnnotation]:
    """Budgeted span annotations, highest score first. Same inputs → same output."""
    first_seen: dict[str, tuple[int, Demand, Concept]] = {}
    for order, d in enumerate(sorted(doc.demands, key=lambda d: (d.anchor.start, d.id))):
        concept = graph.get(d.target_id) if d.target_id else None
        if concept is not None and concept.id not in first_seen:
            first_seen[concept.id] = (order, d, concept)

    scored = []
    for order, d, c in first_seen.values():
        p = p_know(d, c, graph, theta)
        s = span_score(d, p)
        if s >= threshold:
            scored.append((s, order, d, c, p))
    scored.sort(key=lambda row: (-row[0], row[1]))

    budget = max(1, word_count(doc) // WORDS_PER_SPAN)
    per_paragraph: dict[str, int] = {}
    chosen: list[SpanAnnotation] = []
    for s, _, d, c, p in scored:
        if len(chosen) >= budget:
            break
        if per_paragraph.get(d.paragraph_id, 0) >= MAX_SPANS_PER_PARAGRAPH:
            continue
        per_paragraph[d.paragraph_id] = per_paragraph.get(d.paragraph_id, 0) + 1
        chosen.append(_annotation(d, c, graph, p, s))
    return chosen


def _annotation(d: Demand, c: Concept, graph: ConceptGraph, p: float, s: float) -> SpanAnnotation:
    return SpanAnnotation(
        demand_id=d.id,
        paragraph_id=d.paragraph_id,
        anchor=d.anchor,
        concept_id=c.id,
        label=c.label,
        definition=c.definition,
        domain=c.domain,
        base_difficulty=c.base_difficulty,
        prerequisites=tuple(q.label for q in graph.prerequisites(c.id))[:3],
        p_know=p,
        salience=d.salience,
        score=s,
    )
