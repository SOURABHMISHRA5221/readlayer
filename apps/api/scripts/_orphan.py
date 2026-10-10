"""Find (and with --delete, remove) the users/{uid} tree whose log hash matches. Approved by
Sourabh 2026-10-10 for uid_hash 47fc3fc4b90aee7d (his own 12:28 IST session)."""
import asyncio
import sys

from google.cloud import firestore

from app.config import get_settings
from app.log import hash_uid
from app.store.docstore import get_doc_store
from app.store.reader_repo import USER_SUBCOLLECTIONS


async def main(target: str, delete: bool) -> None:
    settings = get_settings()
    db = firestore.AsyncClient(project=settings.db_project)
    ids = [ref.id async for ref in db.collection("users").list_documents()]
    match = [u for u in ids if hash_uid(u, settings.uid_hash_salt) == target]
    if len(match) != 1:
        raise SystemExit(f"expected exactly one match, found {len(match)}")
    uid = match[0]
    store = get_doc_store()
    paths = [f"users/{uid}"] if await store.get(f"users/{uid}") else []
    for sub in USER_SUBCOLLECTIONS:
        paths += [f"users/{uid}/{sub}/{d}" for d, _ in await store.list(f"users/{uid}/{sub}")]
    print("docs:", len(paths))
    for p in paths:
        print("  ", p.replace(uid, "<uid>"))
    if delete:
        if len(paths) != 8:
            raise SystemExit("refusing: the approved count was 8")
        print("deleted:", await store.delete_tree(f"users/{uid}"))
        print("left:", len([d async for d in db.collection("users").document(uid).collections()]),
              "subcollections; user doc exists:", (await db.document(f"users/{uid}").get()).exists)


asyncio.run(main(sys.argv[1], "--delete" in sys.argv))
