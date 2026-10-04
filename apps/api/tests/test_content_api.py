import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import llm
from app.ingest import safe_fetch as sf
from app.ingest.safe_fetch import FetchedPage, FetchError
from app.main import app
from app.store.content_repo import InMemoryContentStore, set_content_store
from tests.fakes import FakeLLM, auth

FIXTURE = (Path(__file__).parent / "fixtures" / "article_business.html").read_bytes()
URL = "https://news.example/rbi"


def reply(_vars):
    return {
        "paragraphs": [
            {
                "paragraph_id": "p0",
                "structurally_dense": False,
                "items": [
                    {
                        "exact": "repo rate",
                        "label": "Repo rate",
                        "type": "concept",
                        "salience": 0.9,
                        "explained_in_text": False,
                    }
                ],
            }
        ]
    }


class FakeFetcher:
    def __init__(self, error: FetchError | None = None) -> None:
        self.error = error
        self.urls: list[str] = []

    async def fetch(self, url: str) -> FetchedPage:
        self.urls.append(url)
        if self.error:
            raise self.error
        return FetchedPage(url, FIXTURE, "utf-8")


@pytest.fixture
def store():
    s = InMemoryContentStore()
    set_content_store(s)
    yield s
    set_content_store(None)


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


client = TestClient(app, headers=auth("writer"))


def test_url_shape_ingests_and_stores(store, fetcher, fake_llm):
    resp = client.post("/v1/content", json={"url": URL})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["title"] == "RBI holds repo rate at 6.5% as inflation cools"
    assert body["paragraphs"][0]["id"] == "p0"
    doc = store.docs[body["content_id"]]
    assert doc.source == "fetch" and doc.demands[0].anchor.exact == "repo rate"
    assert all(0 <= p.structure <= 1 for p in doc.paragraphs)
    assert doc.llm_calls[0].model == "vertex_ai/fast"


def test_repost_is_a_cache_hit_with_no_fetch_or_llm(store, fetcher, fake_llm, caplog):
    first = client.post("/v1/content", json={"url": URL}).json()
    with caplog.at_level(logging.INFO, logger="app.ingest"):
        second = client.post("/v1/content", json={"url": URL + "?utm_source=tw"}).json()
    assert second == first
    assert len(fake_llm.calls) == 1 and len(fetcher.urls) == 1
    assert any(r.getMessage() == "content cache hit" for r in caplog.records)


def test_extension_shape_ingests_without_fetching(store, fetcher, fake_llm):
    paragraphs = [
        "The Reserve Bank of India kept its repo rate unchanged at 6.5% on Wednesday, the tenth "
        "straight meeting without a move, as retail inflation eased to 3.9% in August.",
        "Bond markets had largely priced in the pause, and the yield on the benchmark 10-year "
        "government bond fell 3 basis points to 6.42%, analysts at two brokerages noted today.",
        "The central bank also left the cash reserve ratio, the share of deposits banks must park "
        "with it, unchanged at 4%, and kept its GDP growth forecast for the year at 6.8%.",
    ]
    resp = client.post(
        "/v1/content", json={"url": URL, "title": "RBI holds", "paragraphs": paragraphs}
    )
    assert resp.status_code == 200, resp.text
    assert fetcher.urls == []
    doc = store.docs[resp.json()["content_id"]]
    assert doc.source == "extension" and [p.text for p in doc.paragraphs] == paragraphs


def test_budget_exceeded_serves_cached_content(store, fetcher, fake_llm):
    first = client.post("/v1/content", json={"url": URL}).json()
    fake_llm.error = llm.BudgetExceeded("over")
    resp = client.post("/v1/content", json={"url": URL})
    assert resp.status_code == 200 and resp.json() == first


def test_budget_exceeded_uncached_is_503_with_retry_after(store, fetcher, fake_llm):
    fake_llm.error = llm.BudgetExceeded("over")
    resp = client.post("/v1/content", json={"url": URL})
    assert resp.status_code == 503
    assert resp.json()["error"] == "llm_budget_exceeded"
    assert 0 < int(resp.headers["retry-after"]) <= 86400
    assert store.docs == {}


def test_llm_unavailable_is_503(store, fetcher, fake_llm):
    fake_llm.error = llm.LLMUnavailable("down")
    resp = client.post("/v1/content", json={"url": URL})
    assert resp.status_code == 503 and resp.headers["retry-after"] == "60"


@pytest.mark.parametrize(
    ("code", "status"),
    [("unsafe_url", 400), ("robots_disallowed", 403), ("not_html", 415), ("timeout", 504)],
)
def test_fetch_errors_mapped(store, fake_llm, code, status):
    sf.set_fetcher(FakeFetcher(FetchError(code, "nope")))
    try:
        resp = client.post("/v1/content", json={"url": URL})
    finally:
        sf.set_fetcher(None)
    assert resp.status_code == status and resp.json()["error"] == code


def test_unsafe_url_rejected_before_cache_or_fetch(store, fetcher, fake_llm):
    resp = client.post("/v1/content", json={"url": "http://169.254.169.254/latest/meta-data"})
    assert resp.status_code == 400 and fetcher.urls == [] and fake_llm.calls == []


def test_too_little_text_is_422(store, fetcher, fake_llm):
    resp = client.post(
        "/v1/content",
        json={"url": URL, "title": "t", "paragraphs": ["Subscribe to read the full story here."]},
    )
    assert resp.status_code == 422 and resp.json()["error"] == "no_article_text"
    assert fake_llm.calls == []
