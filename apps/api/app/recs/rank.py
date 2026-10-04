"""Ranking for "Up next" (pure; no I/O).

    score = relevance × relation_weight × format_affinity × freshness × not_seen

Format affinity is a smoothed rate per reader and format: a Beta prior from the reader's
defaults (demo personas for now, the reader graph in M4) updated by clicks and completions
(successes) and dismissals (failures), with an optional explicit Read / Watch / Listen
preference. Dismissing a card also lowers that relation's weight for the reader.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from app.recs.models import FORMATS, Format, Relation

RELATION_WEIGHT: Mapping[Relation, float] = {
    "primer": 1.0,
    "explainer": 0.95,
    "deeper": 0.9,
    "angle": 0.85,
    "same_story": 0.8,
}
RELATION_LABEL: Mapping[Relation, str] = {
    "primer": "Simpler primer",
    "explainer": "Explainer",
    "deeper": "Go deeper",
    "angle": "Different angle",
    "same_story": "Same story elsewhere",
}

PRIOR_STRENGTH = 4.0  # pseudo-observations behind the persona default
COMPLETION_WEIGHT = 2.0
SHOWN_NO_CLICK_WEIGHT = 0.1
EXPLICIT_MEAN = 0.9
EXPLICIT_OTHERS = 0.6  # other formats' means are scaled by this under an explicit preference
DISMISS_DECAY = 0.6
MIN_RELATION_FACTOR = 0.3
LENGTH_MATCH = 1.2
LENGTH_MISMATCH = 0.85
SHORT_READ_S = 5 * 60
LONG_READ_S = 8 * 60
FRESH_HALF_LIFE_DAYS = 30.0
FRESH_FLOOR = 0.6
UNDATED_FRESHNESS = 0.85
CLICKED_NOT_SEEN = 0.3
OFTEN_SHOWN = 3
OFTEN_SHOWN_NOT_SEEN = 0.8
# Slots per format, most preferred first; MAX_ITEMS is their sum.
FORMAT_QUOTAS = (3, 2, 1)
MAX_ITEMS = sum(FORMAT_QUOTAS)

LengthPref = Literal["short", "long"] | None
SeenState = Literal["clicked", "completed", "dismissed"]


@dataclass(frozen=True)
class FormatPrior:
    means: Mapping[Format, float]
    length: LengthPref = None


# Demo defaults (PLACEHOLDER until the reader graph): newcomer watches, the trader skims
# short articles, the policy student reads long.
PERSONA_FORMAT_PRIORS: Mapping[str, FormatPrior] = {
    "newcomer": FormatPrior({"video": 0.75, "article": 0.5, "podcast": 0.45}),
    "trader": FormatPrior({"article": 0.7, "video": 0.45, "podcast": 0.4}, "short"),
    "policy_student": FormatPrior({"article": 0.7, "podcast": 0.55, "video": 0.4}, "long"),
    # Signed-in readers until onboarding (M7) asks: a mild lean to articles, no length pref.
    "default": FormatPrior({"article": 0.6, "video": 0.5, "podcast": 0.45}),
}


@dataclass(frozen=True)
class FormatStats:
    shown: int = 0
    clicks: int = 0
    completions: int = 0
    dismissals: int = 0


@dataclass(frozen=True)
class ReaderSignals:
    formats: Mapping[Format, FormatStats] = field(default_factory=dict)
    relation_dismissals: Mapping[Relation, int] = field(default_factory=dict)
    seen: Mapping[str, SeenState] = field(default_factory=dict)
    shown_counts: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class Candidate:
    id: str
    relation: Relation
    format: Format
    relevance: float
    published_at: str | None = None
    duration_s: int | None = None
    kind: str = "library"  # "library" | "web": select() keeps at least one of each when it can


def format_affinity(
    fmt: Format,
    prior: FormatPrior,
    stats: FormatStats,
    explicit: Format | None = None,
    duration_s: int | None = None,
) -> float:
    """0.5..1.5 (times a length factor for articles): 1.0 means no preference either way."""
    mean = prior.means.get(fmt, 0.5)
    if explicit is not None:
        mean = EXPLICIT_MEAN if fmt == explicit else mean * EXPLICIT_OTHERS
    unanswered = max(0, stats.shown - stats.clicks)
    alpha = PRIOR_STRENGTH * mean + stats.clicks + COMPLETION_WEIGHT * stats.completions
    beta = PRIOR_STRENGTH * (1 - mean) + stats.dismissals + SHOWN_NO_CLICK_WEIGHT * unanswered
    factor = 0.5 + alpha / (alpha + beta)
    if fmt == "article" and prior.length and duration_s:
        short, long_ = duration_s <= SHORT_READ_S, duration_s >= LONG_READ_S
        if (prior.length == "short" and short) or (prior.length == "long" and long_):
            factor *= LENGTH_MATCH
        elif (prior.length == "short" and long_) or (prior.length == "long" and short):
            factor *= LENGTH_MISMATCH
    return factor


def relation_weight(relation: Relation, dismissals: int) -> float:
    return RELATION_WEIGHT[relation] * max(MIN_RELATION_FACTOR, DISMISS_DECAY**dismissals)


def freshness(published_at: str | None, now: datetime) -> float:
    if not published_at:
        return UNDATED_FRESHNESS
    try:
        when = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    except ValueError:
        return UNDATED_FRESHNESS
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    age_days = max(0.0, (now - when).total_seconds() / 86400)
    return FRESH_FLOOR + (1 - FRESH_FLOOR) * math.pow(0.5, age_days / FRESH_HALF_LIFE_DAYS)


def not_seen(item_id: str, signals: ReaderSignals) -> float:
    state = signals.seen.get(item_id)
    if state in ("completed", "dismissed"):
        return 0.0
    if state == "clicked":
        return CLICKED_NOT_SEEN
    return OFTEN_SHOWN_NOT_SEEN if signals.shown_counts.get(item_id, 0) >= OFTEN_SHOWN else 1.0


def score(
    c: Candidate,
    signals: ReaderSignals,
    prior: FormatPrior,
    now: datetime,
    explicit: Format | None = None,
) -> float:
    return (
        c.relevance
        * relation_weight(c.relation, signals.relation_dismissals.get(c.relation, 0))
        * format_affinity(
            c.format, prior, signals.formats.get(c.format, FormatStats()), explicit, c.duration_s
        )
        * freshness(c.published_at, now)
        * not_seen(c.id, signals)
    )


def format_order(
    signals: ReaderSignals, prior: FormatPrior, explicit: Format | None = None
) -> list[Format]:
    """Formats from most to least preferred: the explicit choice first when there is one,
    then by this reader's affinity (ties in FORMATS order, so it is deterministic)."""
    affinity = {
        f: format_affinity(f, prior, signals.formats.get(f, FormatStats())) for f in FORMATS
    }
    order = sorted(FORMATS, key=lambda f: (-affinity[f], FORMATS.index(f)))
    if explicit is not None:
        order = [explicit, *(f for f in order if f != explicit)]
    return order


def format_quotas(order: Sequence[Format], available: Mapping[Format, int]) -> dict[Format, int]:
    """FORMAT_QUOTAS (3/2/1) down the preference order. A format with too few qualifying
    results passes its spare slots to the next format in order (wrapping round)."""
    quotas = {f: min(q, available.get(f, 0)) for f, q in zip(order, FORMAT_QUOTAS, strict=True)}
    for i, f in enumerate(order):
        spare = FORMAT_QUOTAS[i] - quotas[f]
        for step in range(1, len(order)):
            if spare == 0:
                break
            nxt = order[(i + step) % len(order)]
            extra = min(spare, available.get(nxt, 0) - quotas[nxt])
            if extra > 0:
                quotas[nxt] += extra
                spare -= extra
    return quotas


def select(
    candidates: Sequence[Candidate],
    signals: ReaderSignals,
    prior: FormatPrior,
    now: datetime,
    explicit: Format | None = None,
) -> list[tuple[Candidate, float]]:
    """Up to MAX_ITEMS: the reader's preferred format gets 3 slots, the next two 2 and 1
    (spare slots move down the order). Within a format, best score first, one entry per id.
    If the picks lack a library or a web item while one qualifies, it replaces the weakest
    pick of its own format, so the list mixes both. Final order is by score."""
    scored = sorted(
        ((c, score(c, signals, prior, now, explicit)) for c in candidates),
        key=lambda cs: (-cs[1], cs[0].id),
    )
    best: dict[str, tuple[Candidate, float]] = {}
    for c, s in scored:
        if s > 0 and c.id not in best:
            best[c.id] = (c, s)
    by_format: dict[Format, list[tuple[Candidate, float]]] = {f: [] for f in FORMATS}
    for cs in best.values():
        by_format[cs[0].format].append(cs)

    quotas = format_quotas(
        format_order(signals, prior, explicit), {f: len(v) for f, v in by_format.items()}
    )
    picks = {f: by_format[f][: quotas[f]] for f in FORMATS}

    for kind in ("library", "web"):
        if any(c.kind == kind for chosen in picks.values() for c, _ in chosen):
            continue
        wanted = next((cs for cs in best.values() if cs[0].kind == kind), None)
        if wanted is None or not picks[wanted[0].format]:
            continue
        chosen = picks[wanted[0].format]
        # lowest score; among ties the one ranked last
        weakest = max(range(len(chosen)), key=lambda i: (-chosen[i][1], i))
        chosen[weakest] = wanted

    taken = [cs for chosen in picks.values() for cs in chosen]
    return sorted(taken, key=lambda cs: (-cs[1], cs[0].id))
