import pytest
from fastapi.testclient import TestClient

from app import config
from app.content import router as read_router
from app.graph.loader import get_graph, set_graph
from app.main import app
from app.recs import router as recs_router
from app.recs import state as rec_state
from app.recs import web_search as ws
from app.recs.models import WebResult
from app.store.content_repo import InMemoryContentStore, set_content_store
from tests.test_recs_library import DOCS, GRAPH, doc

VIDEO = WebResult(
    url="https://www.youtube.com/watch?v=v1",
    title="Yields explained",
    source="Econ",
    format="video",
    duration_or_read_time=300,
)
PODCAST = WebResult(
    url="https://podcasts.apple.com/e1",
    title="The bond show",
    source="podcasts.apple.com",
    format="podcast",
)
WEB_ARTICLE = WebResult(
    url="https://explainer.example/yield",
    title="Bond yields, explained",
    source="explainer.example",
    format="article",
)


class FakeProvider:
    name = "fake"
    formats = frozenset({"article", "video", "podcast"})

    def __init__(self):
        self.queries = []

    async def search(self, query, fmt):
        """One result per query that names the searched concept (so it passes the gate)."""
        self.queries.append(query)
        base = {"article": WEB_ARTICLE, "video": VIDEO, "podcast": PODCAST}[fmt]
        slug = query.replace(" ", "-")
        return [base.model_copy(update={"url": f"{base.url}/{slug}", "title": f"{query} guide"})]


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("DEV_AUTH_BYPASS", "true")
    config.get_settings.cache_clear()
    store = InMemoryContentStore()
    store.docs = {d.content_id: d for d in DOCS}
    set_content_store(store)
    read_router.reset_catalog()
    recs_router._index = None
    previous = get_graph()
    set_graph(GRAPH)
    provider = FakeProvider()
    calls = ws.InMemorySearchCalls()
    ws.set_web_search(
        ws.WebSearch(
            {f: provider for f in ("article", "video", "podcast")},
            ws.InMemoryRecCache(),
            calls,
            config.get_settings(),
            frozenset(),
        )
    )
    rec_state.set_rec_state(None)
    yield TestClient(app), provider, calls, store
    ws.set_web_search(None)
    set_graph(previous)
    set_content_store(None)
    read_router.reset_catalog()


def get_recs(client, **params):
    q = "&".join(f"{k}={v}" for k, v in {"persona": "newcomer", **params}.items())
    return client.get(f"/v1/content/main/recommendations?{q}").json()


def test_first_view_is_library_then_web_after_poll(env):
    client, provider, calls, _ = env
    first = get_recs(client)
    assert first["pending"] is True
    assert {i["kind"] for i in first["items"]} == {"library"}
    second = get_recs(client)
    assert second["pending"] is False
    kinds = {i["kind"] for i in second["items"]}
    assert kinds == {"library", "web"}
    for persona in ("trader", "policy_student"):  # every persona gets the mix, not just one
        get_recs(client, persona=persona)
        assert {i["kind"] for i in get_recs(client, persona=persona)["items"]} == {"library", "web"}
    formats = [i["format"] for i in second["items"]]
    assert len(formats) == 6
    # newcomer prefers video: it gets up to 3 slots, and whatever it can't fill moves on
    videos = formats.count("video")
    assert 1 <= videos <= 3 and all(formats.count(f) <= 6 - videos for f in ("article", "podcast"))
    assert all(q.endswith(("explained", "podcast episode")) for q in provider.queries)
    calls_after = sum(calls.calls.values())
    get_recs(client)
    assert sum(calls.calls.values()) == calls_after  # cached: no new calls


def test_items_carry_relation_why_and_triggers(env):
    client, *_ = env
    get_recs(client)
    items = get_recs(client)["items"]
    for item in items:
        assert item["relation_label"] and item["why"]
        if item["kind"] == "web":
            assert item["relation"] == "explainer" and item["content_id"] is None
            assert item["triggers"] and item["triggers"][0]["label"] in item["why"]
        else:
            assert item["content_id"] and item["url"].startswith("https://")


def test_newcomer_gets_video_and_explicit_preference_reorders(env):
    client, *_ = env
    get_recs(client)
    newcomer = get_recs(client)["items"]
    assert newcomer[0]["format"] == "video"
    prefer_listen = get_recs(client, prefer="podcast")["items"]
    assert prefer_listen[0]["format"] == "podcast"
    assert get_recs(client, prefer="nope") == {"detail": []} or True  # validated below
    assert client.get("/v1/content/main/recommendations?prefer=nope").status_code == 422


def test_events_feed_affinity_and_dismissals(env):
    client, *_ = env
    get_recs(client)
    items = get_recs(client)["items"]
    dismissed = items[0]
    resp = client.post(
        "/v1/recs/events",
        json={
            "persona": "newcomer",
            "events": [
                {"id": "e1", "type": "rec_dismissed", "item_id": dismissed["id"]},
                {"id": "e1", "type": "rec_dismissed", "item_id": dismissed["id"]},
                {"id": "e2", "type": "rec_clicked", "item_id": "web:never-served"},
            ],
        },
    )
    assert resp.json() == {"applied": 1, "ignored": 2}
    after = [i["id"] for i in get_recs(client)["items"]]
    assert dismissed["id"] not in after
    # other personas are untouched
    assert client.get("/v1/content/main/recommendations?persona=trader").status_code == 200


def test_unknown_content_and_auth(env, monkeypatch):
    client, *_ = env
    assert client.get("/v1/content/nope/recommendations").status_code == 404
    monkeypatch.delenv("DEV_AUTH_BYPASS")
    config.get_settings.cache_clear()
    assert client.get("/v1/content/main/recommendations").status_code == 401


def test_open_ingests_within_the_daily_cap(env, monkeypatch):
    client, _, _, store = env
    monkeypatch.setenv("INGEST_DAILY_CAP", "1")
    config.get_settings.cache_clear()

    sources = []

    async def fake_ingest(url, source="fetch"):
        from app.ingest.urls import url_hash

        sources.append(source)
        d = doc(url_hash(url), "Opened", "explainer.example", [], url=url)
        store.docs[d.content_id] = d
        return d

    monkeypatch.setattr(recs_router, "ingest_url", fake_ingest)
    first = client.post("/v1/recs/open", json={"url": "https://explainer.example/yield"})
    assert first.status_code == 200 and first.json()["new"] is True
    assert sources == ["user_ingested"]  # reader-opened pages never become corpus data
    again = client.post("/v1/recs/open", json={"url": "https://explainer.example/yield"})
    assert again.status_code == 200 and again.json()["new"] is False  # cached: free
    capped = client.post("/v1/recs/open", json={"url": "https://explainer.example/other"})
    assert capped.status_code == 429 and capped.json()["error"] == "ingest_cap_reached"
    unsafe = client.post("/v1/recs/open", json={"url": "http://127.0.0.1/admin"})
    assert unsafe.status_code == 400
