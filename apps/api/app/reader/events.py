"""Interaction events → reader-model updates (DESIGN §4, §9, §15.2). Pure.

Evidence timestamps use the server's clock, not the client's `at` (untrusted); the client time
is kept on the stored event only. Duplicate ids inside a batch count once; ids already stored
are filtered out by the repository before this runs, so replaying a batch changes nothing.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from app.reader import model
from app.reader.model import Edge

EventType = Literal[
    "explain_opened", "knew_this", "explain_helpful", "report_wrong", "text_searched",
    "annotation_dismissed", "paragraph_dwell",
]  # fmt: skip
CONCEPT_EVENTS: frozenset[str] = frozenset(
    {
        "explain_opened", "knew_this", "explain_helpful", "report_wrong", "text_searched",
        "annotation_dismissed",
    }
)  # fmt: skip
# Graded outcomes for the Elo θ update (DESIGN §4: knew_this, explain_opened; calibration in M7).
ELO_OUTCOME: Mapping[str, float] = {"knew_this": 1.0, "explain_opened": 0.0}
MAX_DWELL_WORDS = 2000  # one paragraph_dwell event can't claim more than this


@dataclass(frozen=True)
class ReaderEvent:
    id: str
    type: EventType
    at: datetime  # client clock, stored only
    concept_id: str | None = None
    content_id: str | None = None
    paragraph_id: str | None = None
    words: int | None = None
    ms: int | None = None


@dataclass(frozen=True)
class ConceptRef:
    domain: str
    difficulty: float


@dataclass(frozen=True)
class EventOutcome:
    edges: dict[str, Edge] = field(default_factory=dict)  # changed edges only
    theta: dict[str, float] = field(default_factory=dict)  # changed domains only
    words_read: int = 0
    applied: tuple[str, ...] = ()
    ignored: tuple[str, ...] = ()
    applied_types: tuple[str, ...] = ()  # in order; drives threshold_offset (scoring.rules)
    content_ids: frozenset[str] = frozenset()  # contents engaged with (context rule)


def apply_events(
    events: Sequence[ReaderEvent],
    edges: Mapping[str, Edge],
    theta: Mapping[str, float],
    concepts: Mapping[str, ConceptRef],
    now: datetime,
    *,
    k: float = model.ELO_K,
) -> EventOutcome:
    """Apply a batch in order. Unknown concepts and repeated ids are ignored."""
    new_edges: dict[str, Edge] = {}
    new_theta: dict[str, float] = {}
    words = 0
    types: list[str] = []
    contents: set[str] = set()
    applied: list[str] = []
    ignored: list[str] = []
    seen: set[str] = set()
    for ev in events:
        if ev.id in seen:
            ignored.append(ev.id)
            continue
        seen.add(ev.id)
        if ev.type == "paragraph_dwell":
            words += max(0, min(ev.words or 0, MAX_DWELL_WORDS))
            applied.append(ev.id)
            types.append(ev.type)
            if ev.content_id:
                contents.add(ev.content_id)
            continue
        ref = concepts.get(ev.concept_id) if ev.concept_id else None
        if ev.type not in CONCEPT_EVENTS or ref is None:
            ignored.append(ev.id)
            continue
        applied.append(ev.id)
        types.append(ev.type)
        if ev.content_id:
            contents.add(ev.content_id)
        w = model.EVIDENCE_WEIGHTS.get(ev.type)
        if w is None:  # report_wrong, annotation_dismissed: stored as events, no evidence
            continue
        th = new_theta.get(ref.domain, theta.get(ref.domain, 0.0))
        p0 = model.prior(th, ref.difficulty)
        cid = ev.concept_id or ""
        edge = new_edges.get(cid) or edges.get(cid) or model.init_edge(p0, now)
        new_edges[cid] = model.apply_evidence(edge, p0, ev.type, w, now)
        if ev.type in ELO_OUTCOME:
            new_theta[ref.domain] = model.elo(th, ELO_OUTCOME[ev.type], ref.difficulty, k)
    return EventOutcome(
        new_edges, new_theta, words, tuple(applied), tuple(ignored), tuple(types),
        frozenset(contents),
    )  # fmt: skip


def correction(
    edge: Edge | None, ref: ConceptRef, theta: Mapping[str, float], known: bool, now: datetime
) -> Edge:
    """PATCH /v1/me/graph: the reader says "I know this" / "I don't". Strong evidence."""
    p0 = model.prior(theta.get(ref.domain, 0.0), ref.difficulty)
    base = edge or model.init_edge(p0, now)
    w = model.STRONG_EVIDENCE if known else -model.STRONG_EVIDENCE
    return model.apply_evidence(base, p0, "correction", w, now)
