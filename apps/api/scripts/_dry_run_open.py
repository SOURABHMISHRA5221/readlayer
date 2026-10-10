"""Read-only dry run before an "Open here" test: is the URL new? What's today's ingest count?"""
import asyncio
import sys

from app.ingest.urls import url_hash
from app.store.content_repo import get_content_store
from app.store.docstore import get_doc_store
from app.store.spend_repo import today_utc


async def main(url: str) -> None:
    cid = url_hash(url)
    store = get_doc_store()
    print("content_id", cid)
    print("contents/", (await get_content_store().get(cid)) is not None)
    print("pending_contents/", (await store.get(f"pending_contents/{cid}")) is not None)
    print("ops/ingest today", await store.get(f"ops/ingest/days/{today_utc()}"))
    print("pending_contents total", len(await store.list("pending_contents")))


asyncio.run(main(sys.argv[1]))
