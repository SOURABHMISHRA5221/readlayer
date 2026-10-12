"""Who may read a doc by id (M8 §A5, DESIGN §17.4).

Extension text can be a subscriber's paywalled article, and its id is derived from the URL, so
it is readable only by the readers who submitted it (their `ingested` list); anyone else gets the
same 404 as an unknown id. Everything else (corpus, "Open here" pages the server fetched itself)
stays readable by id.
"""

from fastapi import HTTPException

from app.ingest.models import ContentDoc, PendingDoc
from app.store.docstore import get_doc_store
from app.store.reader_repo import ReaderRepo

PRIVATE_SOURCES = frozenset({"extension"})


async def require_readable(
    doc: ContentDoc | PendingDoc, uid: str, ingested: frozenset[str] | None = None
) -> None:
    """404 unless this reader may read `doc`. `ingested` when the route already has it; else it
    is read here, for private docs only."""
    if doc.source not in PRIVATE_SOURCES:
        return
    if ingested is None:
        ingested = await ReaderRepo(get_doc_store()).ingested_ids(uid)
    if doc.content_id not in ingested:
        raise HTTPException(status_code=404, detail="content not found")
