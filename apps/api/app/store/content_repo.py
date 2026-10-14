"""Demand profiles, Firestore `contents/{url_hash}` (DESIGN §3). Shared by all readers.

A stored page's text never changes; its demand links can, when a reader's reopen grows concepts
for it (M9 part 1): `claim_growth` and `finish_growth` keep that to one grower per page across
instances, and a run that outlived its claim writes nothing.
"""

import secrets
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any, Literal, Protocol

from google.cloud import firestore

from app.config import get_settings
from app.ingest.models import ContentDoc, Demand, LLMCall

COLLECTION = "contents"

Claim = tuple[Literal["claimed", "busy", "absent"], str | None]


def _claim(doc: dict[str, Any] | None, now: datetime) -> tuple[Claim, dict[str, Any] | None]:
    """The claim decision on a stored doc's fields, and the fields to write when claimed."""
    if doc is None:
        return ("absent", None), None
    until = doc.get("growing_until")
    if until is not None and until > now:
        return ("busy", None), None
    token = secrets.token_hex(8)
    return ("claimed", token), {"grow_token": token}


def _finish_fields(
    doc: dict[str, Any],
    demands: list[Demand] | None,
    calls: list[LLMCall],
    grow_pending: bool,
    grow_tried: list[str],
) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "grow_pending": grow_pending,
        "grow_tried": grow_tried,
        "grow_token": None,
        "growing_until": None,
    }
    if demands is not None:
        fields["demands"] = [d.model_dump() for d in demands]
    if calls:
        fields["llm_calls"] = [*doc.get("llm_calls", []), *(c.model_dump() for c in calls)]
    return fields


class ContentStore(Protocol):
    async def get(self, content_id: str) -> ContentDoc | None: ...

    async def put(self, doc: ContentDoc) -> None: ...

    def iter_all(self) -> AsyncIterator[ContentDoc]: ...

    async def claim_growth(self, content_id: str, now: datetime, until: datetime) -> Claim: ...

    async def finish_growth(
        self,
        content_id: str,
        token: str,
        demands: list[Demand] | None,
        calls: list[LLMCall],
        grow_pending: bool,
        grow_tried: list[str],
    ) -> bool: ...


class FirestoreContentStore:
    def __init__(self, project: str) -> None:
        self._db = firestore.AsyncClient(project=project or None)

    async def get(self, content_id: str) -> ContentDoc | None:
        snap = await self._db.collection(COLLECTION).document(content_id).get()
        return ContentDoc.model_validate(snap.to_dict()) if snap.exists else None

    async def put(self, doc: ContentDoc) -> None:
        await self._db.collection(COLLECTION).document(doc.content_id).set(doc.model_dump())

    async def iter_all(self) -> AsyncIterator[ContentDoc]:
        async for snap in self._db.collection(COLLECTION).stream():
            yield ContentDoc.model_validate(snap.to_dict())

    async def claim_growth(self, content_id: str, now: datetime, until: datetime) -> Claim:
        ref = self._db.collection(COLLECTION).document(content_id)

        @firestore.async_transactional
        async def body(tx: firestore.AsyncTransaction) -> Claim:
            snap = await ref.get(transaction=tx)
            claim, fields = _claim(snap.to_dict() if snap.exists else None, now)
            if fields is not None:
                tx.update(ref, fields | {"growing_until": until})
            return claim

        return await body(self._db.transaction())

    async def finish_growth(
        self,
        content_id: str,
        token: str,
        demands: list[Demand] | None,
        calls: list[LLMCall],
        grow_pending: bool,
        grow_tried: list[str],
    ) -> bool:
        ref = self._db.collection(COLLECTION).document(content_id)

        @firestore.async_transactional
        async def body(tx: firestore.AsyncTransaction) -> bool:
            snap = await ref.get(transaction=tx)
            doc = snap.to_dict() if snap.exists else None
            if doc is None or doc.get("grow_token") != token:
                return False
            tx.update(ref, _finish_fields(doc, demands, calls, grow_pending, grow_tried))
            return True

        return await body(self._db.transaction())


class InMemoryContentStore:
    """For tests and local runs without Firestore."""

    def __init__(self) -> None:
        self.docs: dict[str, ContentDoc] = {}

    async def get(self, content_id: str) -> ContentDoc | None:
        return self.docs.get(content_id)

    async def put(self, doc: ContentDoc) -> None:
        self.docs[doc.content_id] = doc

    async def iter_all(self) -> AsyncIterator[ContentDoc]:
        for doc in list(self.docs.values()):
            yield doc

    async def claim_growth(self, content_id: str, now: datetime, until: datetime) -> Claim:
        doc = self.docs.get(content_id)
        claim, fields = _claim(doc.model_dump() if doc else None, now)
        if doc is not None and fields is not None:
            self.docs[content_id] = doc.model_copy(update=fields | {"growing_until": until})
        return claim

    async def finish_growth(
        self,
        content_id: str,
        token: str,
        demands: list[Demand] | None,
        calls: list[LLMCall],
        grow_pending: bool,
        grow_tried: list[str],
    ) -> bool:
        doc = self.docs.get(content_id)
        if doc is None or doc.grow_token != token:
            return False
        fields = _finish_fields(doc.model_dump(), demands, calls, grow_pending, grow_tried)
        self.docs[content_id] = ContentDoc.model_validate(doc.model_dump() | fields)
        return True


_store: ContentStore | None = None


def get_content_store() -> ContentStore:
    global _store
    if _store is None:
        _store = FirestoreContentStore(get_settings().db_project)
    return _store


def set_content_store(store: ContentStore | None) -> None:
    global _store
    _store = store
