"""Reading-goal progress (M7.5 §C, DESIGN §18). Pure: no I/O, no SDK.

Habit goals count this ISO week's (UTC) reading: an article counts when its annotations load
that week (`weekly.content_ids`), minutes are words read / 230. Learning goals count their
target concepts that are "known": band "understands" or "can explain" (p_know ≥ 0.5).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from app.graph.graph import ConceptGraph
from app.graph.models import Concept
from app.graph.taxonomy import BY_ID
from app.reader import model
from app.reader import onboarding_text as ot
from app.reader.state import ReaderState

WORDS_PER_MINUTE = 230
MAX_TARGETS = 8
MAX_GOALS = 5
KNOWN_P = 0.5
_PREFIXES = ("understand", "learn about", "learn", "get", "know", "grasp")

Metric = Literal["articles", "minutes"]


@dataclass(frozen=True)
class Progress:
    done: float
    total: float
    paused: bool = False

    @property
    def fraction(self) -> float:
        return 0.0 if self.total <= 0 else min(1.0, self.done / self.total)


def strip_prefix(text: str) -> str:
    """ "understand insulin resistance" → "insulin resistance" (the idea, not the verb)."""
    t = " ".join(text.split()).strip(" .!?")
    low = t.casefold()
    for p in _PREFIXES:
        if low.startswith(p + " "):
            return t[len(p) + 1 :].strip()
    return t


def targets(graph: ConceptGraph, concept_id: str) -> list[Concept]:
    """The concept and its prerequisite chain, most basic first, at most 8 (the concept last)."""
    chain = graph.prerequisite_chain(concept_id)
    return chain[-MAX_TARGETS:]


TOPIC_TARGETS = 10


def topic_targets(graph: ConceptGraph, topic: str, phrase: str,
                  limit: int = TOPIC_TARGETS) -> list[Concept]:  # fmt: skip
    """A topic goal's ideas (decision 48): concepts of `topic` whose label or an alias shares a
    whole word with the phrase (the topic's own label word, e.g. "politics", doesn't count),
    most read first (doc_freq, then id); then filled with the topic's most read concepts.
    Concepts never met in the corpus (doc_freq 0) only when the topic has too few others."""
    words = ot.kept_words(phrase) - ot.tokens(BY_ID[topic].label)
    in_topic = sorted((c for c in graph.concepts if c.domain == topic),
                      key=lambda c: (-c.doc_freq, c.id))  # fmt: skip

    def names(c: Concept) -> set[str]:
        return set().union(*(ot.tokens(n) for n in (c.label, *c.aliases)))

    matched = [c for c in in_topic if words & names(c)]
    out = matched[:limit]
    met = [c for c in in_topic if c.doc_freq > 0 and c not in out]
    out += met[: limit - len(out)]
    out += [c for c in in_topic if c not in out][: limit - len(out)]
    return out


def habit_progress(metric: Metric, per_week: int, weekly: Mapping[str, Any] | None,
                   paused: bool) -> Progress:  # fmt: skip
    weekly = weekly or {}
    if metric == "articles":
        done = float(len(weekly.get("content_ids", []) or []))
    else:
        done = round(float(weekly.get("words_read", 0) or 0) / WORDS_PER_MINUTE, 1)
    return Progress(done, float(per_week), paused)


def is_known(concept: Concept, state: ReaderState, now: datetime) -> bool:
    p0 = model.prior(state.theta.get(concept.domain, 0.0), concept.base_difficulty)
    edge = state.edges.get(concept.id)
    p = model.current_p_know(edge, p0, now) if edge is not None else p0
    return p >= KNOWN_P


def learning_progress(graph: ConceptGraph, target_ids: Sequence[str], state: ReaderState,
                      now: datetime) -> Progress:  # fmt: skip
    concepts = [c for cid in target_ids if (c := graph.get(cid)) is not None]
    return Progress(float(sum(is_known(c, state, now) for c in concepts)), float(len(concepts)))
