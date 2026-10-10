"""Onboarding and calibration for signed-in readers (DESIGN §4, §8; M7). Pure: no I/O.

Onboarding turns a few answers into a starting point: θ per domain from the reader's comfort,
interest per domain, analogy frames, and a small nudge from articles they liked. Calibration then
asks 8 quick "do you know this?" taps on common concepts whose difficulty is closest to the
reader's current θ, and each answer is evidence (±) on the concept plus an Elo step on θ.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.graph.graph import ConceptGraph
from app.graph.models import DOMAINS, Concept
from app.graph.taxonomy import BUSINESS_DOMAINS
from app.ingest.models import ContentDoc
from app.reader import model
from app.reader.model import Edge

Level = Literal["new", "some", "comfortable", "expert"]
Answer = Literal["explain", "heard", "none"]
Field = Literal[
    "software", "finance", "commerce", "law", "science", "medicine", "design", "teaching", "other"
]

# The same targets as a profile edit's set_domain_level (DESIGN §15.3), so both paths agree.
LEVEL_THETA: Mapping[Level, float] = {"new": -1.5, "some": -0.5, "comfortable": 0.5, "expert": 1.5}
INTEREST_CHOSEN = 1.0
INTEREST_OTHER = 0.3
# A field suggests an analogy frame in the UI; what the reader picks is what's stored.
FIELD_FRAME: Mapping[str, str] = {
    "software": "software", "law": "law", "science": "science", "medicine": "medicine",
    "design": "design", "teaching": "teaching",
}  # fmt: skip
MAX_THINKS_IN = 3
MAX_LIKED = 3
LIKED_MIN_SALIENCE = 0.7
LIKED_MAX_CONCEPTS = 15

CALIBRATION_ITEMS = 8
POOL_SIZE = 150  # the most frequent concepts per domain: terms a news reader meets
# A domain needs this many concepts before calibration offers it (glossary-seeded domains
# qualify; a domain that only has a few grown concepts doesn't). M2.2.
CALIBRATION_MIN_CONCEPTS = 30
# DESIGN §4: calibration answers are ±3.0. "heard" (knows the word, not the idea) is −1.5 and an
# Elo outcome of 0.5 (M7 rules, recorded in DESIGN §4).
ANSWER_WEIGHT: Mapping[Answer, float] = {"explain": 3.0, "heard": -1.5, "none": -3.0}
ANSWER_OUTCOME: Mapping[Answer, float] = {"explain": 1.0, "heard": 0.5, "none": 0.0}


def starting_theta(comfort: Mapping[str, Level]) -> dict[str, float]:
    """θ for every domain the reader rated; unrated domains stay at the neutral 0."""
    return {d: LEVEL_THETA[level] for d, level in comfort.items() if d in DOMAINS}


def interests(chosen: Iterable[str]) -> dict[str, float]:
    picked = set(chosen)
    return {d: INTEREST_CHOSEN if d in picked else INTEREST_OTHER for d in DOMAINS}


def liked_concepts(docs: Sequence[ContentDoc]) -> list[str]:
    """Linked, salient concepts of the liked articles: each gets a small positive nudge."""
    out: list[str] = []
    for doc in docs[:MAX_LIKED]:
        ranked = sorted(
            (d for d in doc.demands if d.target_id and d.salience >= LIKED_MIN_SALIENCE),
            key=lambda d: (-d.salience, d.target_id),
        )
        seen: list[str] = []
        for d in ranked:
            if d.target_id not in seen:
                seen.append(d.target_id)  # type: ignore[arg-type]
        out += [c for c in seen[:LIKED_MAX_CONCEPTS] if c not in out]
    return out


def calibration_pool(graph: ConceptGraph, domain: str) -> list[Concept]:
    """Most frequent first; glossary seeds and grown concepts (doc_freq 0) offer their most basic
    concepts first, since base_difficulty includes how common the word is."""
    in_domain = [c for c in graph.concepts if c.domain == domain]
    return sorted(in_domain, key=lambda c: (-c.doc_freq, c.base_difficulty, c.id))[:POOL_SIZE]


def calibration_domains(graph: ConceptGraph, interest_domains: Iterable[str]) -> list[str]:
    """The reader's interests that have enough concepts, in taxonomy order; if none qualifies,
    the four business domains (the graph's original core)."""
    counts: dict[str, int] = {}
    for c in graph.concepts:
        counts[c.domain] = counts.get(c.domain, 0) + 1
    picked = set(interest_domains)
    ready = [d for d in DOMAINS if d in picked and counts.get(d, 0) >= CALIBRATION_MIN_CONCEPTS]
    return ready or list(BUSINESS_DOMAINS)


def next_item(
    graph: ConceptGraph,
    interest_domains: Sequence[str],
    theta: Mapping[str, float],
    asked: Sequence[str],
) -> Concept | None:
    """The next calibration concept, or None when all 8 are asked. Round-robin over the reader's
    interest domains that have enough concepts (else the four business domains); within a domain
    the concept whose difficulty is closest to the reader's θ there, never one already asked.
    Deterministic (ties by id)."""
    if len(asked) >= CALIBRATION_ITEMS:
        return None
    domains = calibration_domains(graph, interest_domains)
    done = set(asked)
    start = len(asked) % len(domains)
    for offset in range(len(domains)):
        domain = domains[(start + offset) % len(domains)]
        th = theta.get(domain, 0.0)
        pool = [c for c in calibration_pool(graph, domain) if c.id not in done]
        if pool:
            return min(pool, key=lambda c: (abs(c.base_difficulty - th), c.id))
    return None


@dataclass(frozen=True)
class AnswerOutcome:
    edge: Edge
    theta: float


def apply_answer(
    concept: Concept, edge: Edge | None, theta: float, answer: Answer, now: datetime
) -> AnswerOutcome:
    """Evidence on the concept and an onboarding-strength Elo step on its domain's θ."""
    p0 = model.prior(theta, concept.base_difficulty)
    base = edge or model.init_edge(p0, now)
    new_edge = model.apply_evidence(base, p0, "calibration_answer", ANSWER_WEIGHT[answer], now)
    new_theta = model.elo(
        theta, ANSWER_OUTCOME[answer], concept.base_difficulty, model.ELO_K_ONBOARDING
    )
    return AnswerOutcome(new_edge, new_theta)


def apply_liked(concept: Concept, edge: Edge | None, theta: float, now: datetime) -> Edge:
    p0 = model.prior(theta, concept.base_difficulty)
    base = edge or model.init_edge(p0, now)
    w = model.EVIDENCE_WEIGHTS["liked_article_mention"]
    return model.apply_evidence(base, p0, "liked_article_mention", w, now)
