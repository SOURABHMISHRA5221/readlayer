"""Reader-brought pages are private to the readers who brought them in (M7.5 §B.2)."""

from fastapi.testclient import TestClient

from app.content import router as read_router
from app.ingest.urls import url_hash
from app.main import app
from app.recs import library as lib
from app.recs import router as recs_router
from app.store.docstore import get_doc_store
from app.store.reader_repo import ReaderRepo
from tests.fakes import auth, fake_fetch_and_extract
from tests.test_recs_api import env  # noqa: F401  (fixture)
from tests.test_recs_library import ARTICLE, DOCS, GRAPH

URL = "https://private.example/pasted-page"
CID = url_hash(URL)


def reader(uid):
    return TestClient(app, headers=auth(uid, anonymous=True))


def _store_private(store):
    """A pasted page that would be a strong Up next pick (a copy of the syndicated story)."""
    synd = next(d for d in DOCS if d.content_id == "synd")
    store.docs[CID] = synd.model_copy(
        update={"content_id": CID, "url": URL, "final_url": URL, "source": "user_ingested"}
    )
    read_router.reset_catalog()


def ids(client):
    return {i["id"] for i in client.get("/v1/content?persona=newcomer").json()}


def test_a_pasted_page_shows_only_for_the_readers_who_brought_it_in(env):  # noqa: F811
    _, _, _, store = env
    _store_private(store)
    a, b = reader("judge-a"), reader("judge-b")
    assert CID not in ids(a) and CID not in ids(b)  # nobody has brought it in yet
    assert a.post("/v1/recs/open", json={"url": URL}).json()["ready"] is True
    assert CID in ids(a)
    assert CID not in ids(b)  # same persona template, shared row cache, per-request filter
    assert b.post("/v1/recs/open", json={"url": URL}).status_code == 200  # B pastes it too
    assert CID in ids(b)


def test_up_next_never_offers_another_readers_page_and_keeps_its_slots(env):  # noqa: F811
    _, _, _, store = env
    b = reader("judge-b")
    url = "/v1/content/main/recommendations?persona=newcomer"
    b.get(url)  # first view is library-only while web lookups run; settle them first
    before = b.get(url).json()["items"]
    _store_private(store)
    reader("judge-a").post("/v1/recs/open", json={"url": URL})
    after = b.get(url).json()["items"]
    assert CID not in {i["content_id"] for i in after}
    lib_before = [i for i in before if i["kind"] == "library"]
    lib_after = [i for i in after if i["kind"] == "library"]
    assert len(lib_after) >= len(lib_before)


def test_hidden_pages_are_dropped_before_the_per_relation_cut():
    private = next(d for d in DOCS if d.content_id == "synd").model_copy(
        update={"content_id": "priv", "url": "https://priv.example", "source": "user_ingested"}
    )
    index = lib.LibraryIndex.build([*DOCS, private])
    shown = lib.library_candidates(index, ARTICLE, GRAPH, {"finance": -1.0}, ["c_yield"],
                                   hidden=frozenset({"priv"}))  # fmt: skip
    assert "priv" not in {c.content_id for c in shown}
    plain = lib.library_candidates(lib.LibraryIndex.build(DOCS), ARTICLE, GRAPH,
                                   {"finance": -1.0}, ["c_yield"])  # fmt: skip
    assert [c.content_id for c in shown] == [c.content_id for c in plain]


def test_open_records_the_page_on_the_pending_branch_too(env, monkeypatch):  # noqa: F811
    monkeypatch.setattr(recs_router, "fetch_and_extract", fake_fetch_and_extract())
    a, b = reader("ra"), reader("rb")
    assert a.post("/v1/recs/open", json={"url": URL}).json()["new"] is True
    assert b.post("/v1/recs/open", json={"url": URL}).json() == {
        "content_id": CID, "new": False, "ready": False,
    }  # fmt: skip
    repo = ReaderRepo(get_doc_store())
    import asyncio

    assert CID in asyncio.run(repo.ingested_ids("ra")) and CID in asyncio.run(
        repo.ingested_ids("rb")
    )


def test_ingested_is_exported_and_deleted():
    import asyncio

    repo = ReaderRepo(get_doc_store())
    asyncio.run(repo.add_ingested("u9", "c123", "2026-10-11T00:00:00+00:00"))
    assert asyncio.run(repo.export("u9"))["ingested"] == {
        "c123": {"at": "2026-10-11T00:00:00+00:00"}
    }
    asyncio.run(repo.delete("u9"))
    assert asyncio.run(repo.ingested_ids("u9")) == frozenset()


def test_public_ingests_stay_public(env):  # noqa: F811
    _, _, _, store = env
    a = reader("x1")
    assert {d.content_id for d in DOCS} <= ids(a)  # corpus docs (source fetch) list for everyone
