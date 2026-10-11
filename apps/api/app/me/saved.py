"""Saved articles (Design pass A6, DESIGN §16): GET /v1/me/saved, PUT/DELETE /v1/me/saved/{id}.

`users/{uid}/saved/{content_id}` `{at}`, in USER_SUBCOLLECTIONS (export and delete). Only an
article the reader can see in the library may be saved: a corpus doc, or a page they brought in
themselves. Web-only feed items have no content id and can't be saved (no bare URLs stored).
Signed-in readers need consent; demo readers may save (session data under their uid).
"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path

from app.content import catalog
from app.content.router import ContentSummary, _summaries
from app.context import ReaderContext, hidden_ids, reader_context
from app.me.router import require_consent
from app.store.docstore import get_doc_store
from app.store.reader_repo import sub_path, user_path

router = APIRouter()
MAX_SAVED = 500
CONTENT_ID = r"^[0-9a-f]{32}$"


async def _saved(uid: str) -> dict[str, str]:
    return {
        cid: doc.get("at", "") for cid, doc in await get_doc_store().list(f"{user_path(uid)}/saved")
    }


@router.get("/me/saved", response_model=list[ContentSummary])
async def list_saved(
    ctx: Annotated[ReaderContext, Depends(reader_context)],
) -> list[ContentSummary]:
    saved = await _saved(ctx.uid)
    if not saved:
        return []
    hidden = hidden_ids(await catalog.all_docs(), ctx)
    rows = {s.id: s for s in await _summaries(ctx, ctx.density) if s.id not in hidden}
    order = sorted(saved, key=lambda cid: saved[cid], reverse=True)
    return [rows[cid] for cid in order if cid in rows]


@router.put("/me/saved/{content_id}", status_code=204, responses={404: {}, 409: {}})
async def save(
    content_id: Annotated[str, Path(pattern=CONTENT_ID)],
    ctx: Annotated[ReaderContext, Depends(reader_context)],
) -> None:
    await require_consent(ctx.caller)
    docs = await catalog.all_docs()
    if content_id not in {d.content_id for d in docs} or content_id in hidden_ids(docs, ctx):
        raise HTTPException(status_code=404, detail="content not found")
    saved = await _saved(ctx.uid)
    if content_id not in saved and len(saved) >= MAX_SAVED:
        raise HTTPException(status_code=409, detail="too_many_saved")

    async def body(t):
        t.set(sub_path(ctx.uid, "saved", content_id), {"at": datetime.now(UTC).isoformat()})

    await get_doc_store().run(body)


@router.delete("/me/saved/{content_id}", status_code=204)
async def unsave(
    content_id: Annotated[str, Path(pattern=CONTENT_ID)],
    ctx: Annotated[ReaderContext, Depends(reader_context)],
) -> None:
    async def body(t):
        t.delete(sub_path(ctx.uid, "saved", content_id))

    await get_doc_store().run(body)
