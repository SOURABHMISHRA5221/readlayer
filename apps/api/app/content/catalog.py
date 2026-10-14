"""Every stored doc, loaded once per process and shared by the library list and the
recommender (dev slice: ~300 docs). A new ingest appends; a page whose demand links changed by
growth on reopen (M9) is swapped with `replace` on the instance that grew it (other instances
keep the old links until restart); `reset()` drops everything (tests, or after a backfill)."""

import asyncio

from app.ingest.models import ContentDoc
from app.store.content_repo import get_content_store

_docs: dict[str, ContentDoc] | None = None
_lock = asyncio.Lock()
_version = 0


def reset() -> None:
    global _docs, _version
    _docs = None
    _version += 1


def version() -> int:
    """Changes whenever the doc set changes; derived caches key on it."""
    return _version


async def all_docs() -> list[ContentDoc]:
    global _docs
    async with _lock:
        if _docs is None:
            _docs = {d.content_id: d async for d in get_content_store().iter_all()}
        return sorted(_docs.values(), key=lambda d: (d.title.casefold(), d.content_id))


def add(doc: ContentDoc) -> None:
    """Record a freshly ingested doc without reloading the store."""
    global _version
    if _docs is not None and doc.content_id not in _docs:
        _docs[doc.content_id] = doc
        _version += 1


def replace(doc: ContentDoc) -> None:
    """Swap in a stored page whose demand links changed (M9 /grow); derived caches rekey."""
    global _version
    if _docs is not None:
        _docs[doc.content_id] = doc
        _version += 1


def missing(content_id: str) -> bool:
    """True only when the catalog is loaded and lacks this doc (an unloaded catalog reads the
    whole store on first use, so nothing is missing yet)."""
    return _docs is not None and content_id not in _docs
