"""Onboarding and calibration for signed-in readers (DESIGN §4, §8; M7). Pure: no I/O.

Onboarding turns a few answers into a starting point: θ per domain from the reader's comfort,
interest per domain, analogy frames, and a small nudge from articles they liked. Calibration then
asks 8 quick "do you know this?" taps on common concepts whose difficulty is closest to the
reader's current θ, and each answer is evidence (±) on the concept plus an Elo step on θ.
"""

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Literal

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

CALIBRATION_ITEMS = 6  # decision 68 K4: screen 2's Quick check
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


# Decision 68 K1: what the reader does sets a starting level in its field's domains (first-time
# onboarding only; a redo keeps θ). Design and "other" claim no domain.
FIELD_THETA: Mapping[str, tuple[str, ...]] = {
    "software": ("technology",), "finance": ("finance", "economics"), "commerce": ("business",),
    "law": ("law",), "science": ("science",), "medicine": ("health",), "teaching": ("education",),
    "design": (), "other": (),
}  # fmt: skip


def first_theta(
    field: str, previous_field: str | None, comfort: Mapping[str, Level]
) -> dict[str, float]:
    """θ for a first-time screen 1: the field's domains at "comfortable"; a field changed before
    finishing resets the previous field's domains to 0; `comfort`, when sent, wins per domain."""
    out: dict[str, float] = {}
    if previous_field and previous_field != field:
        out |= {d: 0.0 for d in FIELD_THETA.get(previous_field, ())}
    out |= {d: LEVEL_THETA["comfortable"] for d in FIELD_THETA.get(field, ())}
    return out | starting_theta(comfort)


# Decision 68 K2: a few terms common where the reader reads from start slightly known.
HOME_TERMS = 25
HOME_MIN_DOC_FREQ = 3  # rarer "home" concepts are noise (Arthashastra, Panic of 1837)
HOME_MAX_P = 0.8  # never pushed to "can explain" by a guess


def home_terms(graph: ConceptGraph, country: str | None) -> list[Concept]:
    """The country's most frequent concepts (jurisdiction = country, doc_freq ≥ 3), at most
    HOME_TERMS; none for "other" or no country."""
    if not country or country == "other":
        return []
    found = [
        c for c in graph.concepts if c.jurisdiction == country and c.doc_freq >= HOME_MIN_DOC_FREQ
    ]
    return sorted(found, key=lambda c: (-c.doc_freq, c.id))[:HOME_TERMS]


def apply_home(concept: Concept, edge: Edge | None, theta: float, now: datetime) -> Edge | None:
    """One small `home_country` step, or None (write nothing): once per concept ever, never to
    p ≥ HOME_MAX_P (from the reader's edge when there is one, else the prior), and never a band
    move (it isn't news about the reader, so nothing shows as "moved up")."""
    if edge is not None and any(e.type == "home_country" for e in edge.evidence):
        return None
    p0 = model.prior(theta, concept.base_difficulty)
    base = edge or model.init_edge(p0, now)
    new = model.apply_evidence(
        base, p0, "home_country", model.EVIDENCE_WEIGHTS["home_country"], now
    )
    if model.current_p_know(new, p0, now) >= HOME_MAX_P:
        return None
    return replace(new, band_prev=base.band_prev, band_changed_at=base.band_changed_at)


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


def quick_set(
    graph: ConceptGraph,
    interest_domains: Sequence[str],
    theta: Mapping[str, float],
    asked: Sequence[str],
) -> list[str]:
    """Decision 68 K4b: the whole Quick check at once: the terms already answered, then
    `next_item` repeated (each pick counted as asked) up to CALIBRATION_ITEMS. Pure."""
    picked = list(asked)[:CALIBRATION_ITEMS]
    while len(picked) < CALIBRATION_ITEMS:
        c = next_item(graph, interest_domains, theta, picked)
        if c is None:
            break
        picked.append(c.id)
    return picked


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


# ---------------------------------------------------------------- 2-screen onboarding (decision 41)

DISCOVER_ITEMS = 9  # cards on screen 2
DISCOVER_MIN_ITEMS = 6  # fewer web results than this → library items for the chosen domains
MAX_OFFERED_ITEMS = 27  # items remembered for picks (3 discover calls × 9)
MAX_OFFERED_TERMS = 12  # distinct "Know this?" concepts offered
MAX_PICKS = 9
MAX_KNOW_ANSWERS = 9
PICK_DELTA = 0.15  # "I'd read this" / "Not for me" → ± interest in the item's domain
KNOW_ANSWER: Mapping[bool, Answer] = {True: "explain", False: "none"}


def term_order(concepts: Iterable[Concept], topic: str, theta: Mapping[str, float]) -> list[str]:
    """Candidate "Know this?" terms for one item: only concepts of the item's own topic (a
    sports story named "Column", a culture concept, in the harness run), those met in the corpus
    first (doc_freq > 0: words readers actually meet), then the difficulty closest to the
    reader's θ in that domain (ties by id)."""
    th = theta.get(topic, 0.0)
    ranked = sorted((c for c in concepts if c.domain == topic),
                    key=lambda c: (c.doc_freq == 0, abs(c.base_difficulty - th), c.id))  # fmt: skip
    return [c.id for c in ranked]


def as_written(concept: Concept, text: str) -> bool:
    """An acronym label ("OCT", "GST") counts only where the text writes it in capitals: the
    graph's case-insensitive lookup also finds "Oct." in a date (harness, decision 48)."""
    label = concept.label
    if not (label.isupper() and len(label) <= 6):
        return True
    return re.search(rf"(?<![A-Za-z]){re.escape(label)}(?![A-Za-z])", text) is not None


def offer(
    offered: Mapping[str, Mapping[str, Any]],
    new_items: Sequence[tuple[str, str, Sequence[str]]],
    excluded: Iterable[str],
) -> dict[str, dict[str, Any]]:
    """Remember newly served items: item id → {topic, concept}. An item keeps the term it got
    the first time it was served (stable across re-asks); a new item gets its first candidate
    that isn't excluded (the resolved concepts) or already offered, while fewer than
    MAX_OFFERED_TERMS terms are out, else no term. At most MAX_OFFERED_ITEMS items."""
    out = {k: dict(v) for k, v in offered.items()}
    taken = {v["concept"] for v in out.values() if v.get("concept")}
    skip = set(excluded)
    for item, topic, candidates in new_items:
        if item in out or len(out) >= MAX_OFFERED_ITEMS:
            continue
        term = None
        if len(taken) < MAX_OFFERED_TERMS:
            term = next((c for c in candidates if c not in skip and c not in taken), None)
        if term is not None:
            taken.add(term)
        out[item] = {"topic": topic, "concept": term, "n": len(out)}  # served position (d68)
    return out


def with_pick(interest: float, liked: bool) -> float:
    return min(1.0, max(0.0, interest + (PICK_DELTA if liked else -PICK_DELTA)))


def interests_with_picks(
    chosen: Iterable[str], picks: Mapping[str, Mapping[str, Any]]
) -> dict[str, float]:
    """Chosen topics at 1.0, the rest at 0.3, then every pick's ± delta on top (in pick order),
    so Edit → Continue keeps what the reader said on screen 2."""
    out = interests(chosen)
    for pick in picks.values():
        if pick.get("topic") in out:
            out[pick["topic"]] = with_pick(out[pick["topic"]], bool(pick.get("liked")))
    return out
