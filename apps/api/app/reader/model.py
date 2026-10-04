"""Reader model math (DESIGN §4): IRT prior, KNOWS edges as Beta, forgetting, bands, evidence
weights and the Elo-style domain ability update.

Pure: no I/O, no SDK imports. Edges are immutable; every update returns a new one.
"""

import math
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Literal

Band = Literal["unaware", "heard of", "understands", "can explain"]
BANDS: tuple[Band, ...] = ("unaware", "heard of", "understands", "can explain")

K_PRIOR = 2.0  # pseudo-count strength of the prior on first touch
HALF_LIFE_DAYS = 90.0
MAX_EVIDENCE = 20

# Signed evidence weights: positive adds to α, negative to β (DESIGN §4 table).
EVIDENCE_WEIGHTS: dict[str, float] = {
    "knew_this": 2.0,
    "explain_opened": -1.0,
    "explain_helpful": -0.5,  # on top of the explain_opened that preceded it
    "text_searched": -1.0,
    "read_normal_no_hover": 0.3,
    "slowdown": -0.3,
    "liked_article_mention": 0.2,
}
# Calibration answers, quizzes and explicit corrections ("I know this" / "I don't").
STRONG_EVIDENCE = 3.0

ELO_K = 0.1
ELO_K_ONBOARDING = 0.3


@dataclass(frozen=True)
class Evidence:
    type: str
    w: float  # signed
    at: datetime


@dataclass(frozen=True)
class Edge:
    """users/{uid}/knows/{concept_id}."""

    alpha: float
    beta: float
    last_seen: datetime
    band: Band
    evidence: tuple[Evidence, ...] = ()
    band_prev: Band | None = None
    band_changed_at: datetime | None = None


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def prior(theta: float, difficulty: float) -> float:
    """1PL IRT prior: σ(θ_domain − b)."""
    return sigmoid(theta - difficulty)


def band_of(p: float) -> Band:
    if p < 0.25:
        return "unaware"
    if p < 0.5:
        return "heard of"
    if p < 0.8:
        return "understands"
    return "can explain"


def p_know(edge: Edge) -> float:
    return edge.alpha / (edge.alpha + edge.beta)


def confidence(edge: Edge) -> float:
    return edge.alpha + edge.beta


def init_edge(prior_p: float, now: datetime, k: float = K_PRIOR) -> Edge:
    return Edge(alpha=k * prior_p, beta=k * (1 - prior_p), last_seen=now, band=band_of(prior_p))


def forget(edge: Edge, prior_p: float, now: datetime) -> Edge:
    """Shrink toward the prior with a 90-day half-life. Only α and β change."""
    days = max(0.0, (now - edge.last_seen).total_seconds() / 86400)
    if days == 0:
        return edge
    lam = 0.5 ** (days / HALF_LIFE_DAYS)
    a0, b0 = K_PRIOR * prior_p, K_PRIOR * (1 - prior_p)
    return replace(edge, alpha=a0 + lam * (edge.alpha - a0), beta=b0 + lam * (edge.beta - b0))


def current_p_know(edge: Edge, prior_p: float, now: datetime) -> float:
    """p_know as of `now`, with forgetting applied lazily (nothing is written)."""
    return p_know(forget(edge, prior_p, now))


def apply_evidence(edge: Edge, prior_p: float, kind: str, w: float, now: datetime) -> Edge:
    """Forget up to now, add |w| to α (w > 0) or β (w < 0), and track band changes."""
    base = forget(edge, prior_p, now)
    alpha = base.alpha + max(w, 0.0)
    beta = base.beta + max(-w, 0.0)
    new_band = band_of(alpha / (alpha + beta))
    changed = new_band != edge.band
    return replace(
        base,
        alpha=alpha,
        beta=beta,
        last_seen=max(now, edge.last_seen),
        evidence=(*edge.evidence, Evidence(kind, w, now))[-MAX_EVIDENCE:],
        band=new_band,
        band_prev=edge.band if changed else edge.band_prev,
        band_changed_at=now if changed else edge.band_changed_at,
    )


def elo(theta: float, outcome: float, difficulty: float, k: float = ELO_K) -> float:
    """θ ← θ + K·(outcome − σ(θ − b))."""
    return theta + k * (outcome - sigmoid(theta - difficulty))
