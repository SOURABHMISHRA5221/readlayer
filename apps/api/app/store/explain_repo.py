"""Explanation cache and review queue (DESIGN §7). Shared content, not per-reader data.

explanations/{key}            a verified card, or a definition-only outcome after two
                              rejected drafts (no generated text stored). key =
                              sha1(span_hash | band | thinks_in | style | prompt_version)
explanation_reports/{id}      an entry a reader flagged "This is wrong": the evicted entry,
                              its key and when. No user identifier, so it is not user data;
                              the report_wrong event itself lives in users/{uid}/events.
ops/explain/days/{yyyy-mm-dd} counters: hits, generated, verified_first, verified_retry,
                              definition_fallback, judge_unavailable, capped, reports
"""

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any

from app.store.docstore import Doc, DocStore, Txn

CACHE = "explanations"
DELETE_BATCH = 400  # under Firestore's 500 writes per transaction
REPORTS = "explanation_reports"


def _path(collection: str, doc_id: str) -> str:
    if not doc_id or "/" in doc_id:
        raise ValueError("invalid document id")
    return f"{collection}/{doc_id}"


class ExplainRepo:
    def __init__(self, store: DocStore) -> None:
        self._store = store

    async def get(self, key: str) -> Doc | None:
        return await self._store.get(_path(CACHE, key))

    async def put(self, key: str, entry: Doc) -> None:
        async def body(t: Txn) -> None:
            t.set(_path(CACHE, key), entry)

        await self._store.run(body)

    async def keys_for_spans(self, span_hashes: Iterable[str]) -> list[str]:
        """Cache keys whose entry was made for one of these spans (span or paragraph mode;
        decision 66 retires the cards of re-linked spans)."""
        keys: list[str] = []
        for h in sorted(set(span_hashes)):
            keys += [k for k, _ in await self._store.list_where(CACHE, "span_hash", h)]
        return keys

    async def delete_keys(self, keys: Sequence[str]) -> int:
        """Delete these cache entries, in transactions of at most DELETE_BATCH."""
        for i in range(0, len(keys), DELETE_BATCH):
            batch = keys[i : i + DELETE_BATCH]

            async def body(t: Txn, batch: Sequence[str] = batch) -> None:
                for key in batch:
                    t.delete(_path(CACHE, key))

            await self._store.run(body)
        return len(keys)

    async def evict_to_review(self, key: str, report_id: str, now: datetime) -> bool:
        """Remove the entry and queue it for review, in one transaction. False if it was
        already gone (another reader reported it, or it was never cached)."""

        async def body(t: Txn) -> bool:
            entry = await t.get(_path(CACHE, key))
            if entry is None:
                return False
            t.delete(_path(CACHE, key))
            t.set(_path(REPORTS, report_id), {"key": key, "entry": entry, "reported_at": now})
            return True

        return await self._store.run(body)

    async def count(self, day: str, counts: Mapping[str, int]) -> None:
        async def body(t: Txn) -> None:
            path = f"ops/explain/days/{day}"
            doc: dict[str, Any] = (await t.get(path)) or {"day": day}
            for name, n in counts.items():
                doc[name] = int(doc.get(name, 0)) + n
            t.set(path, doc)

        await self._store.run(body)
