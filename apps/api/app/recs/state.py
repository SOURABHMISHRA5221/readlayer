"""Per-reader Up next signals (DESIGN §16.6) in Firestore `users/{uid}/rec_signals/{key}`.

`key` is the demo persona for anonymous readers, `default` for everyone else. One document
holds format stats, relation dismissals, seen items, show counts, the items we served (so an
event can only name something we actually showed) and recent event ids for idempotency.
Covered by GET /v1/me/export and DELETE /v1/me through reader_repo.USER_SUBCOLLECTIONS.
"""

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Literal

from app.recs.models import Format, Relation
from app.recs.rank import FormatStats, ReaderSignals, SeenState
from app.store.docstore import DocStore, Txn, get_doc_store
from app.store.reader_repo import sub_path

RecEventType = Literal["rec_shown", "rec_clicked", "rec_dismissed", "rec_completed"]
MAX_EVENT_IDS = 500  # most recent ids remembered for idempotency
MAX_SERVED = 300  # most recently served items an event may refer to
DEFAULT_KEY = "default"


@dataclass(frozen=True)
class Served:
    format: Format
    relation: Relation


@dataclass
class RecSignalsDoc:
    formats: dict[Format, FormatStats] = field(default_factory=dict)
    relation_dismissals: dict[Relation, int] = field(default_factory=dict)
    seen: dict[str, SeenState] = field(default_factory=dict)
    shown_counts: dict[str, int] = field(default_factory=dict)
    served: dict[str, tuple[Served, datetime]] = field(default_factory=dict)
    event_ids: list[str] = field(default_factory=list)

    @classmethod
    def from_doc(cls, doc: dict[str, Any] | None) -> "RecSignalsDoc":
        doc = doc or {}
        return cls(
            formats={k: FormatStats(**v) for k, v in doc.get("formats", {}).items()},
            relation_dismissals=dict(doc.get("relation_dismissals", {})),
            seen=dict(doc.get("seen", {})),
            shown_counts=dict(doc.get("shown_counts", {})),
            served={
                k: (Served(v["format"], v["relation"]), v["at"])
                for k, v in doc.get("served", {}).items()
            },
            event_ids=list(doc.get("event_ids", [])),
        )

    def to_doc(self) -> dict[str, Any]:
        return {
            "formats": {k: vars(v) for k, v in self.formats.items()},
            "relation_dismissals": dict(self.relation_dismissals),
            "seen": dict(self.seen),
            "shown_counts": dict(self.shown_counts),
            "served": {
                k: {"format": s.format, "relation": s.relation, "at": at}
                for k, (s, at) in self.served.items()
            },
            "event_ids": list(self.event_ids),
        }

    def signals(self) -> ReaderSignals:
        return ReaderSignals(
            dict(self.formats), dict(self.relation_dismissals), dict(self.seen),
            dict(self.shown_counts),
        )  # fmt: skip


def remember(doc: RecSignalsDoc, items: dict[str, Served], now: datetime) -> None:
    doc.served.update({k: (v, now) for k, v in items.items()})
    if len(doc.served) > MAX_SERVED:
        newest = sorted(doc.served.items(), key=lambda kv: (kv[1][1], kv[0]))[-MAX_SERVED:]
        doc.served = dict(newest)


def apply_event(doc: RecSignalsDoc, event_id: str, kind: RecEventType, item_id: str) -> bool:
    """Apply one event in place; False if it was a repeat or names an item we never served."""
    served = doc.served.get(item_id)
    if event_id in doc.event_ids or served is None:
        return False
    fmt, relation = served[0].format, served[0].relation
    doc.event_ids = [*doc.event_ids, event_id][-MAX_EVENT_IDS:]
    stats = doc.formats.get(fmt, FormatStats())
    if kind == "rec_shown":
        doc.formats[fmt] = replace(stats, shown=stats.shown + 1)
        doc.shown_counts[item_id] = doc.shown_counts.get(item_id, 0) + 1
    elif kind == "rec_clicked":
        doc.formats[fmt] = replace(stats, clicks=stats.clicks + 1)
        doc.seen.setdefault(item_id, "clicked")
    elif kind == "rec_completed":
        doc.formats[fmt] = replace(stats, completions=stats.completions + 1)
        doc.seen[item_id] = "completed"
    elif kind == "rec_dismissed":
        doc.formats[fmt] = replace(stats, dismissals=stats.dismissals + 1)
        doc.relation_dismissals[relation] = doc.relation_dismissals.get(relation, 0) + 1
        doc.seen[item_id] = "dismissed"
    return True


class RecSignalsRepo:
    def __init__(self, store: DocStore) -> None:
        self._store = store

    async def signals(self, uid: str, key: str) -> ReaderSignals:
        return RecSignalsDoc.from_doc(
            await self._store.get(sub_path(uid, "rec_signals", key))
        ).signals()

    async def remember_served(
        self, uid: str, key: str, items: dict[str, Served], now: datetime
    ) -> None:
        path = sub_path(uid, "rec_signals", key)

        async def body(t: Txn) -> None:
            doc = RecSignalsDoc.from_doc(await t.get(path))
            remember(doc, items, now)
            t.set(path, doc.to_doc())

        await self._store.run(body)

    async def apply(self, uid: str, key: str, events: list[tuple[str, RecEventType, str]]) -> int:
        path = sub_path(uid, "rec_signals", key)

        async def body(t: Txn) -> int:
            doc = RecSignalsDoc.from_doc(await t.get(path))
            applied = sum(apply_event(doc, eid, kind, item) for eid, kind, item in events)
            if applied:
                t.set(path, doc.to_doc())
            return applied

        return await self._store.run(body)


def get_rec_signals() -> RecSignalsRepo:
    return RecSignalsRepo(get_doc_store())
