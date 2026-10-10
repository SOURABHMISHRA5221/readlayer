"""Articles fetched but not yet analysed, Firestore `pending_contents/{url_hash}`.

Two-phase "Open here": phase 1 stores the extracted article here so the reader sees it at once;
phase 2 (POST /v1/content/{id}/analyse) takes a lease, runs demand extraction and linking, writes
`contents/` and deletes the pending doc. The lease is taken in a transaction so only one instance
spends on an article; it outlives the analysis timeout, so an expired lease always means the
earlier run has already stopped. Shared content, no user data: outside export and delete.
"""

from datetime import datetime, timedelta
from typing import Literal

from app.ingest.models import PendingDoc
from app.store.docstore import DocStore, Txn, get_doc_store

COLLECTION = "pending_contents"
PENDING_TTL = timedelta(hours=24)
MAX_ATTEMPTS = 3

Acquire = Literal["acquired", "busy", "missing", "exhausted"]


class AnalysisBusy(Exception):
    """Another request holds the lease on this article's analysis."""


class AnalysisFailed(Exception):
    """This article's analysis failed MAX_ATTEMPTS times; it won't be retried."""


class NotPending(Exception):
    """No pending doc (and no content) for this id."""


def _path(content_id: str) -> str:
    return f"{COLLECTION}/{content_id}"


class PendingRepo:
    def __init__(self, store: DocStore) -> None:
        self._store = store

    async def get(self, content_id: str) -> PendingDoc | None:
        data = await self._store.get(_path(content_id))
        return PendingDoc.model_validate(data) if data else None

    async def create(self, doc: PendingDoc) -> PendingDoc:
        """Store a freshly extracted article unless another request already did; returns the
        stored one either way (its paragraphs are the ones every reader sees)."""

        async def body(txn: Txn) -> PendingDoc:
            existing = await txn.get(_path(doc.content_id))
            if existing:
                return PendingDoc.model_validate(existing)
            txn.set(_path(doc.content_id), doc.model_dump())
            return doc

        return await self._store.run(body)

    async def acquire(
        self, content_id: str, now: datetime, lease: timedelta
    ) -> tuple[Acquire, PendingDoc | None]:
        async def body(txn: Txn) -> tuple[Acquire, PendingDoc | None]:
            data = await txn.get(_path(content_id))
            if not data:
                return "missing", None
            doc = PendingDoc.model_validate(data)
            if doc.attempts >= MAX_ATTEMPTS:
                return "exhausted", doc
            if doc.lease_until is not None and doc.lease_until > now:
                return "busy", doc
            leased = doc.model_copy(update={"lease_until": now + lease})
            txn.set(_path(content_id), leased.model_dump())
            return "acquired", leased

        return await self._store.run(body)

    async def release(self, content_id: str, *, failed: bool) -> None:
        """Drop the lease; `failed` counts the attempt (an analysis that ran and failed)."""

        async def body(txn: Txn) -> None:
            data = await txn.get(_path(content_id))
            if not data:
                return
            doc = PendingDoc.model_validate(data)
            update = {"lease_until": None, "attempts": doc.attempts + (1 if failed else 0)}
            txn.set(_path(content_id), doc.model_copy(update=update).model_dump())

        await self._store.run(body)

    async def delete(self, content_id: str) -> None:
        async def body(txn: Txn) -> None:
            txn.delete(_path(content_id))

        await self._store.run(body)


def get_pending_repo() -> PendingRepo:
    return PendingRepo(get_doc_store())
