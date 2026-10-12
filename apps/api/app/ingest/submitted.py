"""Extension submissions: POST /v1/content with `{url, title, paragraphs}` (M8, DESIGN §8).

Client text is unverified, so it lives under its own id (`urls.ext_id`) and is readable only by
the readers who submitted it (`content.access`). Before anything new is stored, a request may be
answered by a doc that already exists: the fetch path's doc for the URL (stored or pending), or
the reader's own newest extension doc for it, so a reload of a live page doesn't re-ingest.
"""

import asyncio

from app.ingest.models import ContentDoc, PendingDoc
from app.ingest.urls import normalize_url, url_hash
from app.store.content_repo import get_content_store
from app.store.docstore import get_doc_store
from app.store.pending_repo import get_pending_repo
from app.store.reader_repo import ReaderRepo

AnyDoc = ContentDoc | PendingDoc


async def get_any(content_id: str) -> AnyDoc | None:
    """The stored doc, else the pending one."""
    return await get_content_store().get(content_id) or await get_pending_repo().get(content_id)


async def reusable(uid: str, url: str) -> AnyDoc | None:
    """A doc this reader may be given for `url` without a new ingest, or None."""
    if doc := await get_any(url_hash(url)):
        return doc
    wanted = normalize_url(url)
    ids = await ReaderRepo(get_doc_store()).ingested_newest_first(uid)
    for doc in await asyncio.gather(*(get_any(cid) for cid in ids)):
        if doc is not None and doc.source == "extension" and doc.url == wanted:
            return doc
    return None


async def onboarded(uid: str) -> bool:
    return (await ReaderRepo(get_doc_store()).get_user(uid)).onboarding_done
