"""Minimal document store over slash paths ("users/u1/knows/c_x"), with transactions.

Repositories for per-user data are written once against this interface; Firestore backs it in
the API and the emulator tests, the in-memory store backs unit tests. A transaction body reads
first and then buffers writes (Firestore's rule); it may be retried on contention, so it must
not have side effects beyond the transaction.
"""

from __future__ import annotations

import asyncio
import copy
import logging
import random
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Protocol, TypeVar

from google.api_core.exceptions import Aborted
from google.cloud import firestore

log = logging.getLogger(__name__)

T = TypeVar("T")
Doc = dict[str, Any]


class _ServerTime:
    """Marker for a top-level field the store sets to its own clock on write (Firestore's
    server timestamp), so a skewed instance clock can't misorder documents (M2.2 growth)."""

    def __repr__(self) -> str:
        return "SERVER_TIME"


SERVER_TIME: Any = _ServerTime()


class Txn(Protocol):
    async def get(self, path: str) -> Doc | None: ...

    async def get_all(self, paths: list[str]) -> dict[str, Doc | None]: ...

    def set(self, path: str, data: Doc) -> None: ...

    def delete(self, path: str) -> None: ...


class DocStore(Protocol):
    async def get(self, path: str) -> Doc | None: ...

    async def list(self, collection: str) -> list[tuple[str, Doc]]: ...

    async def list_since(self, collection: str, field: str, after: Any) -> list[tuple[str, Doc]]:
        """Documents of `collection` whose `field` is greater than `after` (one indexed query)."""
        ...

    async def list_where(self, collection: str, field: str, value: Any) -> list[tuple[str, Doc]]:
        """Documents of `collection` whose `field` equals `value` (one indexed query)."""
        ...

    async def delete_tree(self, path: str) -> int: ...

    async def run(self, body: Callable[[Txn], Awaitable[T]]) -> T: ...


# ---------------------------------------------------------------- Firestore

CONTENTION_ROUNDS = 3  # after the client's own 5 attempts


async def retry_contention[R](
    attempt: Callable[[], Awaitable[R]], rounds: int = CONTENTION_ROUNDS
) -> R:
    """Concurrent transactions on one document (e.g. three prefetched explanations reserving
    the same daily counter) can exhaust the client's retries; back off with jitter and try again
    rather than failing the request. The body is idempotent by design (reads, then writes)."""
    for n in range(rounds + 1):
        try:
            return await attempt()
        except (ValueError, Aborted) as exc:
            # Commit-time contention is a ValueError; contention while the body reads surfaces
            # as Aborted (decision 65: an explain 500 seen live). Each round is a new transaction.
            contended = isinstance(exc, Aborted) or "Failed to commit transaction" in str(exc)
            if not contended or n == rounds:
                raise
            await asyncio.sleep(random.uniform(0.05, 0.2) * (n + 1))
    raise AssertionError("unreachable")


class _FirestoreTxn:
    def __init__(self, db: firestore.AsyncClient, txn: firestore.AsyncTransaction) -> None:
        self._db = db
        self._txn = txn

    async def get(self, path: str) -> Doc | None:
        snap = await self._db.document(path).get(transaction=self._txn)
        return snap.to_dict() if snap.exists else None

    async def get_all(self, paths: list[str]) -> dict[str, Doc | None]:
        out: dict[str, Doc | None] = dict.fromkeys(paths)
        if not paths:
            return out
        refs = [self._db.document(p) for p in paths]
        async for snap in self._db.get_all(refs, transaction=self._txn):
            if snap.exists:
                out[snap.reference.path] = snap.to_dict()
        return out

    def set(self, path: str, data: Doc) -> None:
        resolved = {
            k: firestore.SERVER_TIMESTAMP if v is SERVER_TIME else v for k, v in data.items()
        }
        self._txn.set(self._db.document(path), resolved)

    def delete(self, path: str) -> None:
        self._txn.delete(self._db.document(path))


class FirestoreDocStore:
    def __init__(self, project: str) -> None:
        self._db = firestore.AsyncClient(project=project or None)

    async def get(self, path: str) -> Doc | None:
        snap = await self._db.document(path).get()
        return snap.to_dict() if snap.exists else None

    async def list(self, collection: str) -> list[tuple[str, Doc]]:
        return [(s.id, s.to_dict() or {}) async for s in self._db.collection(collection).stream()]

    async def list_since(self, collection: str, field: str, after: Any) -> list[tuple[str, Doc]]:
        query = self._db.collection(collection).where(
            filter=firestore.FieldFilter(field, ">", after)
        )
        return [(s.id, s.to_dict() or {}) async for s in query.stream()]

    async def list_where(self, collection: str, field: str, value: Any) -> list[tuple[str, Doc]]:
        query = self._db.collection(collection).where(
            filter=firestore.FieldFilter(field, "==", value)
        )
        return [(s.id, s.to_dict() or {}) async for s in query.stream()]

    async def delete_tree(self, path: str) -> int:
        """Delete a document and every subcollection under it. Tried once more when it raises:
        a write that fails against the reader's in-flight writes is re-queued by the library
        after its BulkWriter closed ("BulkWriter is closed…", seen live, decision 65). The delete
        is idempotent, and each try gets a new BulkWriter."""
        ref = self._db.document(path)
        try:
            count = await self._db.recursive_delete(ref)
        except Exception:
            log.warning("recursive delete failed; retrying once")
            count = await self._db.recursive_delete(ref)
        await ref.delete()  # recursive_delete covers subcollections; make sure the doc goes too
        return count

    async def run(self, body: Callable[[Txn], Awaitable[T]]) -> T:
        @firestore.async_transactional
        async def wrapped(txn: firestore.AsyncTransaction) -> T:
            return await body(_FirestoreTxn(self._db, txn))

        return await retry_contention(lambda: wrapped(self._db.transaction()))


# ---------------------------------------------------------------- in memory


class _MemoryTxn:
    def __init__(self, docs: dict[str, Doc]) -> None:
        self._docs = docs
        self.writes: dict[str, Doc | None] = {}

    async def get(self, path: str) -> Doc | None:
        if self.writes:
            raise RuntimeError("transaction reads must come before writes")
        return copy.deepcopy(self._docs.get(path))

    async def get_all(self, paths: list[str]) -> dict[str, Doc | None]:
        return {p: await self.get(p) for p in paths}

    def set(self, path: str, data: Doc) -> None:
        now = datetime.now(UTC)
        self.writes[path] = {
            k: now if v is SERVER_TIME else copy.deepcopy(v) for k, v in data.items()
        }

    def delete(self, path: str) -> None:
        self.writes[path] = None


class InMemoryDocStore:
    """For tests and local runs without Firestore. Records every path written."""

    def __init__(self) -> None:
        self.docs: dict[str, Doc] = {}
        self.written: set[str] = set()
        self._lock = asyncio.Lock()

    async def get(self, path: str) -> Doc | None:
        return copy.deepcopy(self.docs.get(path))

    async def list(self, collection: str) -> list[tuple[str, Doc]]:
        depth = collection.count("/") + 1
        return sorted(
            (p.rsplit("/", 1)[1], copy.deepcopy(d))
            for p, d in self.docs.items()
            if p.startswith(collection + "/") and p.count("/") == depth
        )

    async def list_since(self, collection: str, field: str, after: Any) -> list[tuple[str, Doc]]:
        return [(i, d) for i, d in await self.list(collection) if d.get(field) and d[field] > after]

    async def list_where(self, collection: str, field: str, value: Any) -> list[tuple[str, Doc]]:
        return [(i, d) for i, d in await self.list(collection) if d.get(field) == value]

    async def delete_tree(self, path: str) -> int:
        doomed = [p for p in self.docs if p == path or p.startswith(path + "/")]
        for p in doomed:
            del self.docs[p]
        return len(doomed)

    async def run(self, body: Callable[[Txn], Awaitable[T]]) -> T:
        async with self._lock:
            txn = _MemoryTxn(self.docs)
            result = await body(txn)
            for path, data in txn.writes.items():
                self.written.add(path)
                if data is None:
                    self.docs.pop(path, None)
                else:
                    self.docs[path] = data
            return result


_store: DocStore | None = None


def get_doc_store() -> DocStore:
    global _store
    if _store is None:
        from app.config import get_settings

        _store = FirestoreDocStore(get_settings().db_project)
    return _store


def set_doc_store(store: DocStore | None) -> None:
    global _store
    _store = store
