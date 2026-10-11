"""Saved articles (Design pass A6): save, list, unsave, visibility, consent, data rights."""

import asyncio

from fastapi.testclient import TestClient

from app.content import router as read_router
from app.ingest.urls import url_hash
from app.main import app
from app.store.docstore import get_doc_store
from app.store.reader_repo import ReaderRepo
from tests.fakes import auth, consented
from tests.test_recs_api import env  # noqa: F401  (fixture)
from tests.test_recs_library import DOCS

CORPUS = url_hash("https://corpus.example/story")
PRIVATE = url_hash("https://private.example/pasted")


def _store(store):
    main = next(d for d in DOCS if d.content_id == "main")
    store.docs[CORPUS] = main.model_copy(update={"content_id": CORPUS})
    store.docs[PRIVATE] = main.model_copy(update={"content_id": PRIVATE, "source": "user_ingested"})
    read_router.reset_catalog()


def demo(uid):
    return TestClient(app, headers=auth(uid, anonymous=True))


def test_save_list_and_unsave_newest_first(env):  # noqa: F811
    _store(env[3])
    c = demo("saver")
    other = next(d.content_id for d in DOCS if d.content_id == "main")
    assert c.put(f"/v1/me/saved/{CORPUS}").status_code == 204
    assert c.get("/v1/me/saved").json()[0]["id"] == CORPUS
    assert c.put(f"/v1/me/saved/{CORPUS}").status_code == 204  # idempotent
    assert len(c.get("/v1/me/saved").json()) == 1
    assert c.delete(f"/v1/me/saved/{CORPUS}").status_code == 204
    assert c.get("/v1/me/saved").json() == []
    assert c.put(f"/v1/me/saved/{other}").status_code == 422  # not a content id shape


def test_only_visible_articles_can_be_saved(env):  # noqa: F811
    _store(env[3])
    c = demo("peeker")
    assert c.put(f"/v1/me/saved/{PRIVATE}").status_code == 404  # another reader's pasted page
    assert c.put(f"/v1/me/saved/{'0' * 32}").status_code == 404  # unknown


def test_signed_in_readers_need_consent_and_saved_is_exported_and_deleted(env):  # noqa: F811
    _store(env[3])
    google = TestClient(app, headers=auth("g-saver"))
    assert google.put(f"/v1/me/saved/{CORPUS}").status_code == 403
    consented(google)
    assert google.put(f"/v1/me/saved/{CORPUS}").status_code == 204
    repo = ReaderRepo(get_doc_store())
    assert CORPUS in asyncio.run(repo.export("g-saver"))["saved"]
    asyncio.run(repo.delete("g-saver"))
    assert asyncio.run(get_doc_store().list("users/g-saver/saved")) == []
