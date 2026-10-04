"""Per-reader recommendation signals and the daily ingest counter, held in API memory.

Deliberately not in Firestore yet: CLAUDE.md requires every user-data collection to be
covered by export and delete, which arrive in M3. Until then this state lives per
(uid, persona) in the process and resets on restart. Swap for a Firestore repo in M3.
"""

from collections import OrderedDict
from dataclasses import dataclass, field, replace
from typing import Literal

from app.recs.models import Format, Relation
from app.recs.rank import FormatStats, ReaderSignals, SeenState
from app.store.spend_repo import today_utc

RecEventType = Literal["rec_shown", "rec_clicked", "rec_dismissed", "rec_completed"]
MAX_EVENT_IDS = 2000  # remembered per reader for idempotency


@dataclass(frozen=True)
class Served:
    format: Format
    relation: Relation


@dataclass
class _Reader:
    formats: dict[Format, FormatStats] = field(default_factory=dict)
    relation_dismissals: dict[Relation, int] = field(default_factory=dict)
    seen: dict[str, SeenState] = field(default_factory=dict)
    shown_counts: dict[str, int] = field(default_factory=dict)
    served: dict[str, Served] = field(default_factory=dict)
    event_ids: OrderedDict[str, None] = field(default_factory=OrderedDict)


class RecState:
    def __init__(self) -> None:
        self._readers: dict[tuple[str, str], _Reader] = {}
        self._ingests: dict[tuple[str, str], int] = {}  # (uid, utc day) → new URLs ingested

    def _reader(self, uid: str, persona: str) -> _Reader:
        return self._readers.setdefault((uid, persona), _Reader())

    def signals(self, uid: str, persona: str) -> ReaderSignals:
        r = self._reader(uid, persona)
        return ReaderSignals(
            dict(r.formats), dict(r.relation_dismissals), dict(r.seen), dict(r.shown_counts)
        )

    def remember_served(self, uid: str, persona: str, items: dict[str, Served]) -> None:
        self._reader(uid, persona).served.update(items)

    def apply(
        self, uid: str, persona: str, event_id: str, kind: RecEventType, item_id: str
    ) -> bool:
        """Apply one event; False if it was a repeat or names an item we never served."""
        r = self._reader(uid, persona)
        served = r.served.get(item_id)
        if event_id in r.event_ids or served is None:
            return False
        r.event_ids[event_id] = None
        while len(r.event_ids) > MAX_EVENT_IDS:
            r.event_ids.popitem(last=False)
        stats = r.formats.get(served.format, FormatStats())
        if kind == "rec_shown":
            r.formats[served.format] = replace(stats, shown=stats.shown + 1)
            r.shown_counts[item_id] = r.shown_counts.get(item_id, 0) + 1
        elif kind == "rec_clicked":
            r.formats[served.format] = replace(stats, clicks=stats.clicks + 1)
            if r.seen.get(item_id) is None:
                r.seen[item_id] = "clicked"
        elif kind == "rec_completed":
            r.formats[served.format] = replace(stats, completions=stats.completions + 1)
            r.seen[item_id] = "completed"
        elif kind == "rec_dismissed":
            r.formats[served.format] = replace(stats, dismissals=stats.dismissals + 1)
            r.relation_dismissals[served.relation] = (
                r.relation_dismissals.get(served.relation, 0) + 1
            )
            r.seen[item_id] = "dismissed"
        return True

    def ingests_today(self, uid: str) -> int:
        return self._ingests.get((uid, today_utc()), 0)

    def count_ingest(self, uid: str) -> None:
        key = (uid, today_utc())
        self._ingests[key] = self._ingests.get(key, 0) + 1


_state = RecState()


def get_rec_state() -> RecState:
    return _state


def set_rec_state(state: RecState | None) -> None:
    global _state
    _state = state or RecState()
