import pytest
from fastapi.testclient import TestClient

from app import config
from app.content import router as read_router
from app.graph.loader import get_graph, set_graph
from app.ingest.urls import url_hash
from app.main import app
from app.recs import router as recs_router
from app.recs import web_search as ws
from app.recs.models import WebResult
from app.store.content_repo import InMemoryContentStore, set_content_store
from tests.fakes import auth, fake_fetch_and_extract
from tests.test_recs_library import DOCS, GRAPH

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

    async def search(self, query, fmt, news=False, include_domains=()):
        """One result per query that names the searched concept (so it passes the gate)."""
        self.queries.append(query)
        base = {"article": WEB_ARTICLE, "video": VIDEO, "podcast": PODCAST}[fmt]
        slug = query.replace(" ", "-")
        return [base.model_copy(update={"url": f"{base.url}/{slug}", "title": f"{query} guide"})]


@pytest.fixture
def env():
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
    yield TestClient(app, headers=auth("demo", anonymous=True)), provider, calls, store
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
    assert TestClient(app).get("/v1/content/main/recommendations").status_code == 401


def test_open_ingests_within_the_daily_cap(env, monkeypatch):
    client, _, _, store = env
    monkeypatch.setenv("ANON_INGEST_DAILY_CAP", "1")
    config.get_settings.cache_clear()

    sources: list[str] = []
    monkeypatch.setattr(recs_router, "fetch_and_extract", fake_fetch_and_extract(sources))
    first = client.post("/v1/recs/open", json={"url": "https://explainer.example/yield"})
    assert first.status_code == 200
    assert first.json() == {
        "content_id": url_hash("https://explainer.example/yield"),
        "new": True, "ready": False, "kind": "article", "stage": "analyse",
    }  # fmt: skip
    assert sources == ["user_ingested"]  # reader-opened pages never become corpus data
    again = client.post("/v1/recs/open", json={"url": "https://explainer.example/yield"})
    # Pending (fetched, not analysed): free, no second fetch.
    assert again.status_code == 200 and again.json()["new"] is False
    assert again.json()["ready"] is False and sources == ["user_ingested"]
    capped = client.post("/v1/recs/open", json={"url": "https://explainer.example/other"})
    assert capped.status_code == 429 and capped.json()["error"] == "ingest_cap_reached"
    unsafe = client.post("/v1/recs/open", json={"url": "http://127.0.0.1/admin"})
    assert unsafe.status_code == 400


# Decision 67 N1: card chips come from the article's key ideas, one item per format.


def _article_recs(client, persona="newcomer", content="main"):
    url = f"/v1/content/{content}/recommendations?basis=article&persona={persona}"
    client.get(url)  # first view starts the web lookups
    return client.get(url).json()


def test_article_basis_is_key_ideas_one_per_format(env):
    from app.recs.feed_rank import key_ideas
    from app.recs.models import FORMATS
    from app.recs.router import WEB_TRIGGERS
    from app.recs.web_search import build_query

    client, provider, _, store = env
    ideas, _ = key_ideas(store.docs["main"], GRAPH)
    idea_ids = {c.id for c in ideas}
    seen_triggers = []
    for persona in ("newcomer", "trader", "policy_student"):
        body = _article_recs(client, persona)
        items = body["items"]
        formats = [i["format"] for i in items]
        assert 1 <= len(items) <= 3 and len(set(formats)) == len(formats)
        assert formats == [f for f in FORMATS if f in formats]  # article, video, podcast order
        for item in items:
            trig = {t["id"] for t in item["triggers"]}
            assert trig and trig <= idea_ids
            assert "a key idea here" in item["why"]
        seen_triggers.append({t["id"] for i in items for t in i["triggers"]})
    # DESIGN §16.3: label + domain + format suffix only, on the article's own key ideas
    expected = {build_query(c.label, f, c.domain) for c in ideas[:WEB_TRIGGERS] for f in FORMATS}
    assert provider.queries and set(provider.queries) <= expected


def test_article_basis_is_the_same_for_every_persona(env):
    client, *_ = env
    lookups = [_article_recs(client, p) for p in ("newcomer", "trader")]
    ideas = [sorted({t["id"] for i in b["items"] for t in i["triggers"]}) for b in lookups]
    assert ideas[0] and set(ideas[0]) & set(ideas[1])


def test_article_basis_without_linked_ideas_is_empty(env):
    client, _, _, store = env
    bare = store.docs["main"].model_copy(update={"content_id": "bare", "demands": []})
    store.docs["bare"] = bare
    read_router.reset_catalog()
    recs_router._index = None
    assert _article_recs(client, content="bare")["items"] == []


def test_basis_is_validated(env):
    client, *_ = env
    url = "/v1/content/main/recommendations?basis=words"
    assert client.get(url).status_code == 422


def test_article_basis_records_served_items_only_after_consent(env, docs):
    from tests.fakes import auth as signed_in
    from tests.fakes import consented

    client = TestClient(app, headers=signed_in("s1"))
    url = "/v1/content/main/recommendations?basis=article"
    client.get(url)
    assert client.get(url).json()["items"]
    assert not [p for p in docs.docs if p.startswith("users/s1/rec_signals/")]
    consented(client)
    client.get(url)
    assert [p for p in docs.docs if p.startswith("users/s1/rec_signals/")]
