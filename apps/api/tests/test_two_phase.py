"""Two-phase "Open here": phase 1 shows the article, phase 2 (analyse) adds the notes."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import config, llm
from app.content import catalog
from app.ingest import safe_fetch as sf
from app.ingest import service
from app.ingest.urls import url_hash
from app.main import app
from app.store.content_repo import InMemoryContentStore, set_content_store
from app.store.pending_repo import MAX_ATTEMPTS, get_pending_repo
from tests.fakes import FakeLLM, auth
from tests.test_content_api import FakeFetcher, reply

URL = "https://explainer.example/term-premium"
CID = url_hash(URL)
SHORT_HTML = b"<html><head><title>Stub</title></head><body><p>Subscribe to read.</p></body></html>"


@pytest.fixture
def store():
    s = InMemoryContentStore()
    set_content_store(s)
    catalog.reset()
    yield s
    set_content_store(None)
    catalog.reset()


@pytest.fixture
def fetcher():
    f = FakeFetcher()
    sf.set_fetcher(f)
    yield f
    sf.set_fetcher(None)


@pytest.fixture
def fake_llm(monkeypatch):
    fake = FakeLLM(reply)
    monkeypatch.setattr(llm, "run_with_meta", fake)
    return fake


def client(uid: str = "reader", anonymous: bool = False) -> TestClient:
    return TestClient(app, headers=auth(uid, anonymous=anonymous))


def test_phase_one_shows_the_article_without_any_llm_call(store, fetcher, fake_llm, docs):
    c = client()
    opened = c.post("/v1/recs/open", json={"url": URL})
    assert opened.status_code == 200, opened.text
    assert opened.json() == {"content_id": CID, "new": True, "ready": False}
    assert fake_llm.calls == []  # no extract_demands, no linking
    assert store.docs == {}  # nothing in contents/ yet

    detail = c.get(f"/v1/content/{CID}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["status"] == "analysing" and body["paragraphs"]
    assert body["title"] == "RBI holds repo rate at 6.5% as inflation cools"
    # Notes and recommendations wait for phase 2.
    assert c.get(f"/v1/content/{CID}/annotations").status_code == 409
    assert c.get(f"/v1/content/{CID}/recommendations").status_code == 409
    # The pending doc is shared content: no uid anywhere in it.
    pending = docs.docs[f"pending_contents/{CID}"]
    assert "reader" not in repr(pending)


def test_analyse_keeps_the_paragraphs_and_runs_once(store, fetcher, fake_llm):
    c = client()
    c.post("/v1/recs/open", json={"url": URL})
    shown = c.get(f"/v1/content/{CID}").json()["paragraphs"]

    done = c.post(f"/v1/content/{CID}/analyse")
    assert done.status_code == 200 and done.json() == {"content_id": CID, "status": "ready"}
    assert [call["task"] for call in fake_llm.calls] == ["extract_demands"]
    final = c.get(f"/v1/content/{CID}").json()
    assert final["status"] == "ready"
    assert final["paragraphs"] == shown  # same ids, same text: anchors land where the reader is
    assert store.docs[CID].source == "user_ingested"
    assert c.get(f"/v1/content/{CID}/annotations").status_code == 200

    again = c.post(f"/v1/content/{CID}/analyse")
    assert again.status_code == 200 and len(fake_llm.calls) == 1  # cached, no LLM call
    assert c.post("/v1/content/0123abcd/analyse").status_code == 404


async def _pending(url: str = URL) -> None:
    from tests.fakes import pending_doc

    await get_pending_repo().create(pending_doc(url, texts=[" ".join(["word"] * 120)]))


def test_a_held_lease_gives_202_and_never_a_second_run(store, fake_llm):
    asyncio.run(_pending())
    lease = timedelta(seconds=150)
    status, _ = asyncio.run(get_pending_repo().acquire(CID, datetime.now(UTC), lease))
    assert status == "acquired"
    busy = client().post(f"/v1/content/{CID}/analyse")
    assert busy.status_code == 202 and busy.json()["status"] == "analysing"
    assert fake_llm.calls == []


def test_the_lease_outlives_the_analysis_timeout(store):
    # An expired lease must mean the earlier run already stopped: the timeout fires first.
    s = config.get_settings()
    assert timedelta(seconds=s.analyse_timeout_s) + service.LEASE_MARGIN > timedelta(
        seconds=s.analyse_timeout_s
    )
    asyncio.run(_pending())
    repo = get_pending_repo()
    t0 = datetime.now(UTC)
    lease = timedelta(seconds=s.analyse_timeout_s) + service.LEASE_MARGIN
    assert asyncio.run(repo.acquire(CID, t0, lease))[0] == "acquired"
    still_running = t0 + timedelta(seconds=s.analyse_timeout_s)  # timeout fires here
    assert asyncio.run(repo.acquire(CID, still_running, lease))[0] == "busy"
    after = t0 + lease + timedelta(seconds=1)
    assert asyncio.run(repo.acquire(CID, after, lease))[0] == "acquired"


def test_a_slow_analysis_times_out_and_counts_one_attempt(store, monkeypatch):
    monkeypatch.setenv("ANALYSE_TIMEOUT_S", "0.05")
    config.get_settings.cache_clear()

    async def slow(*_a, **_k):
        await asyncio.sleep(1)

    monkeypatch.setattr(service, "extract_demands", slow)
    asyncio.run(_pending())
    resp = client().post(f"/v1/content/{CID}/analyse")
    assert resp.status_code == 504 and resp.json()["error"] == "analyse_timeout"
    pending = asyncio.run(get_pending_repo().get(CID))
    assert pending is not None and pending.attempts == 1 and pending.lease_until is None


def test_budget_refusals_do_not_count_but_failures_do(store, monkeypatch):
    asyncio.run(_pending())
    c = client()
    monkeypatch.setattr(llm, "run_with_meta", FakeLLM(error=llm.BudgetExceeded("spent")))
    for _ in range(MAX_ATTEMPTS + 1):
        assert c.post(f"/v1/content/{CID}/analyse").status_code == 503
    assert asyncio.run(get_pending_repo().get(CID)).attempts == 0  # nothing ran

    monkeypatch.setattr(llm, "run_with_meta", FakeLLM(error=llm.LLMUnavailable("down")))
    for _ in range(MAX_ATTEMPTS):
        assert c.post(f"/v1/content/{CID}/analyse").status_code == 503
    gone = c.post(f"/v1/content/{CID}/analyse")
    assert gone.status_code == 410 and gone.json()["error"] == "analyse_failed"


def test_post_content_on_a_pending_url_neither_fetches_nor_reserves(store, fetcher, fake_llm, docs):
    asyncio.run(_pending())
    resp = client("writer").post("/v1/content", json={"url": URL})
    assert resp.status_code == 200, resp.text
    assert fetcher.urls == []  # reused the pending article
    assert CID in store.docs and f"pending_contents/{CID}" not in docs.docs
    assert not [p for p in docs.docs if "/ingest_counts/" in p and "writer" in p]


def test_open_on_a_pending_url_is_free_for_the_next_reader(store, fetcher, monkeypatch):
    monkeypatch.setenv("ANON_INGEST_DAILY_CAP", "1")
    config.get_settings.cache_clear()
    first = client("a1", anonymous=True)
    assert first.post("/v1/recs/open", json={"url": URL}).status_code == 200
    second = client("a2", anonymous=True)
    other = "https://explainer.example/other"
    assert second.post("/v1/recs/open", json={"url": URL}).json()["new"] is False
    assert len(fetcher.urls) == 1
    # a2's own slot is still free.
    assert second.post("/v1/recs/open", json={"url": other}).status_code == 200


def test_phase_one_failure_refunds_the_slot(store, monkeypatch):
    monkeypatch.setenv("ANON_INGEST_DAILY_CAP", "1")
    config.get_settings.cache_clear()

    class Stub(FakeFetcher):
        async def fetch(self, url):
            self.urls.append(url)
            return sf.FetchedPage(url, SHORT_HTML, "utf-8")

    sf.set_fetcher(Stub())
    try:
        c = client("a1", anonymous=True)
        stub = c.post("/v1/recs/open", json={"url": URL})
        assert stub.status_code == 422 and stub.json()["error"] == "no_article_text"
        assert asyncio.run(get_pending_repo().get(CID)) is None
        sf.set_fetcher(FakeFetcher())
        # The refunded slot is usable.
        assert c.post("/v1/recs/open", json={"url": URL}).status_code == 200
    finally:
        sf.set_fetcher(None)


def test_analyse_by_another_reader_charges_no_growth_slots(store, fake_llm, monkeypatch):
    from app.ingest import quota

    async def never(*a, **k):
        raise AssertionError("phase 2 must not reserve growth slots")

    monkeypatch.setattr(quota, "reserve_growth", never)
    asyncio.run(_pending())
    resp = client("someone-else", anonymous=True).post(f"/v1/content/{CID}/analyse")
    assert resp.status_code == 200 and resp.json()["status"] == "ready"
