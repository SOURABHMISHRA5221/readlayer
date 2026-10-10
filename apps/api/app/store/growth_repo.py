"""Concepts grown online from ingested articles, Firestore `graph_growth/{concept_id}` (M2.2).

Shared graph data, no user data: each doc is a Concept plus `added_at` (the store's own clock),
`source_cid` (the content id it was grown from) and `prompt_versions`. Every instance merges these
into its in-memory graph at startup and polls for new ones (app/graph/refresh.py); a script folds
them into concepts.json later (scripts/fold_growth.py). Docs are created only if absent, so two
instances growing the same slug never overwrite each other.

Growth slots per UTC day are counted per reader (`users/{uid}/growth_counts/{day}`, a user
subcollection covered by export and delete) and for the whole service (`ops/growth/days/{day}`),
reserved together in one transaction when the article is first fetched (phase 1).
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.graph.models import Concept
from app.store.docstore import SERVER_TIME, DocStore, Txn, get_doc_store
from app.store.reader_repo import sub_path

COLLECTION = "graph_growth"


def day_path(day: str) -> str:
    return f"ops/growth/days/{day}"


@dataclass(frozen=True)
class GrownConcept:
    concept: Concept
    added_at: datetime | None
    source_cid: str


class GrowthRepo:
    def __init__(self, store: DocStore) -> None:
        self._store = store

    async def create_if_absent(
        self, concept: Concept, source_cid: str, prompt_versions: dict[str, str]
    ) -> bool:
        """True if stored; False if a concept with this id already exists (another instance)."""
        path = f"{COLLECTION}/{concept.id}"

        async def body(t: Txn) -> bool:
            if await t.get(path):
                return False
            doc: dict[str, Any] = concept.model_dump()
            doc |= {
                "added_at": SERVER_TIME,
                "source_cid": source_cid,
                "prompt_versions": prompt_versions,
            }
            t.set(path, doc)
            return True

        return await self._store.run(body)

    async def get(self, concept_id: str) -> GrownConcept | None:
        doc = await self._store.get(f"{COLLECTION}/{concept_id}")
        return _grown(doc) if doc else None

    async def since(self, after: datetime | None) -> list[GrownConcept]:
        rows = (
            await self._store.list(COLLECTION)
            if after is None
            else await self._store.list_since(COLLECTION, "added_at", after)
        )
        return [_grown(doc) for _, doc in rows]

    async def reserve_slots(self, uid: str, day: str, want: int, uid_cap: int, day_cap: int) -> int:
        """Grant up to `want` growth slots within the reader's and the service's daily caps;
        returns how many were granted (0 = none, nothing written)."""

        async def body(t: Txn) -> int:
            mine_path, all_path = sub_path(uid, "growth_counts", day), day_path(day)
            reads = await t.get_all([mine_path, all_path])
            mine = int((reads[mine_path] or {}).get("count", 0))
            total = int((reads[all_path] or {}).get("count", 0))
            granted = max(0, min(want, uid_cap - mine, day_cap - total))
            if granted:
                t.set(mine_path, {"count": mine + granted, "day": day})
                t.set(all_path, {"count": total + granted, "day": day})
            return granted

        return await self._store.run(body)

    async def used_today(self, day: str) -> int:
        return int((await self._store.get(day_path(day)) or {}).get("count", 0))


def _grown(doc: dict[str, Any]) -> GrownConcept:
    fields = {k: v for k, v in doc.items() if k in Concept.model_fields}
    return GrownConcept(
        Concept.model_validate(fields), doc.get("added_at"), doc.get("source_cid", "")
    )


def get_growth_repo() -> GrowthRepo:
    return GrowthRepo(get_doc_store())
