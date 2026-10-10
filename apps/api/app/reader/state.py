"""What the scorer knows about one reader (DESIGN §4–6). Pure data, no I/O.

A signed-in reader's state comes from `users/{uid}` (+ domains, knows); a demo reader's from
`users/{uid}/demo_graphs/{persona}`, or the persona's read-only template until their first
event (copy-on-write, app/store/reader_repo.py).
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal, get_args

from app.reader.model import Edge

PersonaKey = Literal["newcomer", "trader", "policy_student"]
PERSONA_KEYS: tuple[PersonaKey, ...] = ("newcomer", "trader", "policy_student")
Density = Literal["minimal", "balanced", "guided"]
ExplanationStyle = Literal["short", "normal", "detailed"]
# Analogy frames explanations may use (DESIGN §7, §15.1 item 5); a reader picks at most 3.
ThinksIn = Literal[
    "software", "engineering", "science", "medicine", "law", "design", "teaching", "music",
    "cooking", "cricket", "football", "gaming",
]  # fmt: skip
THINKS_IN: tuple[ThinksIn, ...] = get_args(ThinksIn)

ENGAGED_WINDOW = timedelta(days=30)  # DESIGN §5 context rule
MAX_ENGAGED = 50  # most recent engaged contents kept per reader
OFFSET_LIMIT = 0.15


@dataclass(frozen=True)
class ReaderState:
    theta: Mapping[str, float] = field(default_factory=dict)
    edges: Mapping[str, Edge] = field(default_factory=dict)
    threshold_offset: float = 0.0
    engaged: Mapping[str, datetime] = field(default_factory=dict)  # content_id → last engaged
    prompts: Mapping[str, tuple[str, ...]] = field(default_factory=dict)  # UTC day → content ids
    # A demo session's own analogy frames for this persona (set by a profile edit), else empty.
    thinks_in: tuple[str, ...] = ()
    # Changes whenever the stored state changes; derived caches key on it.
    rev: str = "neutral"

    def recent_contents(self, now: datetime) -> tuple[str, ...]:
        """Contents engaged with in the last 30 days, sorted."""
        return tuple(sorted(c for c, at in self.engaged.items() if now - at <= ENGAGED_WINDOW))


def clamp_offset(offset: float) -> float:
    return max(-OFFSET_LIMIT, min(OFFSET_LIMIT, offset))


def touch_engaged(
    engaged: Mapping[str, datetime], content_ids: set[str], now: datetime
) -> dict[str, datetime]:
    """Mark contents engaged at `now`, keeping the most recent MAX_ENGAGED."""
    merged = dict(engaged) | dict.fromkeys(content_ids, now)
    keep = sorted(merged.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)[:MAX_ENGAGED]
    return dict(keep)
