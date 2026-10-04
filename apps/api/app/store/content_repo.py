"""Demand profiles, Firestore `contents/{url_hash}` (DESIGN §3). Shared by all readers."""

from typing import Protocol

from google.cloud import firestore

from app.config import get_settings
from app.ingest.models import ContentDoc

COLLECTION = "contents"


class ContentStore(Protocol):
    async def get(self, content_id: str) -> ContentDoc | None: ...

    async def put(self, doc: ContentDoc) -> None: ...


class FirestoreContentStore:
    def __init__(self, project: str) -> None:
        self._db = firestore.AsyncClient(project=project or None)

    async def get(self, content_id: str) -> ContentDoc | None:
        snap = await self._db.collection(COLLECTION).document(content_id).get()
        return ContentDoc.model_validate(snap.to_dict()) if snap.exists else None

    async def put(self, doc: ContentDoc) -> None:
        await self._db.collection(COLLECTION).document(doc.content_id).set(doc.model_dump())


class InMemoryContentStore:
    """For tests and local runs without Firestore."""

    def __init__(self) -> None:
        self.docs: dict[str, ContentDoc] = {}

    async def get(self, content_id: str) -> ContentDoc | None:
        return self.docs.get(content_id)

    async def put(self, doc: ContentDoc) -> None:
        self.docs[doc.content_id] = doc


_store: ContentStore | None = None


def get_content_store() -> ContentStore:
    global _store
    if _store is None:
        _store = FirestoreContentStore(get_settings().gcp_project)
    return _store


def set_content_store(store: ContentStore | None) -> None:
    global _store
    _store = store
