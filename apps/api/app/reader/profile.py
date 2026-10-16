"""Reading profile (DESIGN §15.1–15.2): the deterministic summary template, weekly band changes
and the annotation trend. Pure, and never an LLM call: same inputs give the same text.
"""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.reader.model import BANDS, Edge

LEVELS = ("advanced", "comfortable", "building", "new to")
# How each level reads before a domain list: "comfortable in finance", "new to policy".
PHRASE = {"advanced": "advanced in", "comfortable": "comfortable in", "building": "building in",
          "new to": "new to"}  # fmt: skip
WEEK = timedelta(days=7)
# Evidence that sets or moves a topic's level (decision 69 A2): a profile edit's level, a Quick
# check answer, and the reading events that take an Elo step. Home terms, liked-article mentions,
# persona seeds, corrections and named-concept edits record ideas only, never a level.
LEVEL_EVIDENCE = frozenset(
    {"profile_edit_domain", "calibration_answer", "knew_this", "explain_opened"}
)


def rated_domains(
    theta: Mapping[str, float],
    comfort: Iterable[str],
    edges: Mapping[str, Edge],
    domain_of: Callable[[str], str | None],
) -> set[str]:
    """Topics whose level was set or moved: a comfort answer, θ off its neutral 0, or level-setting
    evidence (which can leave θ at exactly 0: an edit from 0.5 to "some", a "heard of" answer on a
    term as hard as θ). A neutral 0 with only recorded ideas isn't "comfortable" (decision 69
    A2)."""
    rated = {d for d, t in theta.items() if abs(t) > 1e-9} | set(comfort)
    for cid, edge in edges.items():
        if any(e.type in LEVEL_EVIDENCE for e in edge.evidence) and (d := domain_of(cid)):
            rated.add(d)
    return rated


def theta_word(theta: float) -> str:
    """Judged on θ as shown (one decimal), so the page's numbers and words never disagree."""
    theta = round(theta, 1)
    if theta >= 1:
        return "advanced"
    if theta >= 0:
        return "comfortable"
    if theta >= -1:
        return "building"
    return "new to"


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def summary_text(theta: Mapping[str, float], thinks_in: Iterable[str], moved_up: int) -> str:
    """ "Comfortable in finance, building in economics. You think in software. 6 concepts moved
    up a band this week." Domains are grouped by level, strongest first, names alphabetical."""
    groups: dict[str, list[str]] = {}
    for domain in sorted(theta):
        groups.setdefault(theta_word(theta[domain]), []).append(domain)
    parts = [f"{PHRASE[level]} {_join(groups[level])}" for level in LEVELS if level in groups]
    sentences = []
    if parts:
        first = ", ".join(parts)
        sentences.append(first[0].upper() + first[1:] + ".")
    frames = sorted(set(thinks_in))
    if frames:
        sentences.append(f"You think in {_join(frames)}.")
    if moved_up:
        noun = "concept" if moved_up == 1 else "concepts"
        sentences.append(f"{moved_up} {noun} moved up a band this week.")
    return " ".join(sentences)


def top_domain(theta: Mapping[str, float]) -> str | None:
    if not theta:
        return None
    return min(theta, key=lambda d: (-theta[d], d))


@dataclass(frozen=True)
class BandMove:
    concept_id: str
    from_band: str
    to_band: str
    at: datetime


def moved_up_this_week(edges: Mapping[str, Edge], now: datetime) -> list[BandMove]:
    """Concepts whose latest band change, within the last 7 days, was upward."""
    moves = [
        BandMove(cid, e.band_prev, e.band, e.band_changed_at)
        for cid, e in edges.items()
        if e.band_prev is not None
        and e.band_changed_at is not None
        and now - e.band_changed_at <= WEEK
        and BANDS.index(e.band) > BANDS.index(e.band_prev)
    ]
    return sorted(moves, key=lambda m: (-m.at.timestamp(), m.concept_id))


def iso_week(at: datetime) -> str:
    year, week, _ = at.isocalendar()
    return f"{year}-W{week:02d}"


def annotation_trend(weekly: Mapping[str, Mapping[str, float]]) -> list[tuple[str, float]]:
    """Annotations per 1,000 words read, per ISO week with reading recorded, oldest first."""
    out = []
    for week in sorted(weekly):
        words = float(weekly[week].get("words_read", 0) or 0)
        if words > 0:
            shown = float(weekly[week].get("annotations_shown", 0) or 0)
            out.append((week, round(shown / words * 1000, 1)))
    return out
