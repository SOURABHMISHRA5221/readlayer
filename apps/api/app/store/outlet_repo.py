"""Collected outlet articles (decision 50): `rec_cache/outlets:<topic>` = {outlet_id: {items,
fetched_at}}. Shared public data, no reader data. Written only by the collection job (merged
per outlet: an outlet that failed this run keeps its previous list); read by the feed, never
through the search cache (no staleness refetch, never a search)."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.recs.models import WebResult
from app.recs.outlet_feed import merge
from app.store.docstore import DocStore, Txn

COLLECTION = "rec_cache"


def outlets_path(topic: str) -> str:
    return f"{COLLECTION}/outlets:{topic}"


@dataclass(frozen=True)
class OutletList:
    outlet_id: str
    items: tuple[WebResult, ...]
    fetched_at: str


class OutletStore:
    def __init__(self, store: DocStore) -> None:
        self._store = store

    async def read(self, topics: Sequence[str]) -> dict[str, list[OutletList]]:
        """topic → its outlets' lists (missing topics map to [])."""
        out: dict[str, list[OutletList]] = {}
        for topic in dict.fromkeys(topics):
            doc = await self._store.get(outlets_path(topic)) or {}
            out[topic] = [
                OutletList(
                    oid,
                    tuple(WebResult.model_validate(i) for i in entry.get("items", [])),
                    str(entry.get("fetched_at", "")),
                )
                for oid, entry in sorted(doc.items())
                if isinstance(entry, dict)
            ]
        return out

    async def merge_topic(
        self, topic: str, fresh: Mapping[str, Sequence[WebResult]], now: datetime
    ) -> dict[str, int]:
        """Merge this run's items per outlet into the topic's doc. Outlets absent from `fresh`
        (failed this run) keep their items and `fetched_at`; the age filter is re-applied to
        every outlet's list, so stale items leave even while an outlet keeps failing.
        Returns outlet → items now stored."""

        async def body(t: Txn) -> dict[str, int]:
            doc = await t.get(outlets_path(topic)) or {}
            for oid in sorted(set(doc) | set(fresh)):
                raw = doc.get(oid)
                entry: dict[str, Any] = raw if isinstance(raw, dict) else {}
                before = [WebResult.model_validate(i) for i in entry.get("items", [])]
                kept = merge(before, fresh.get(oid, ()), now)
                stamp = (
                    now.isoformat(timespec="seconds")
                    if oid in fresh
                    else entry.get("fetched_at", "")
                )
                doc[oid] = {"items": [r.model_dump() for r in kept], "fetched_at": stamp}
            t.set(outlets_path(topic), doc)
            return {oid: len(e.get("items", [])) for oid, e in doc.items()}

        return await self._store.run(body)
