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


def test_a_signed_in_reader_who_chose_listen_gets_the_listen_chip_first(env, docs):
    """Decision 68 F2: the card chips lead with the reader's chosen format."""
    from tests.fakes import auth as signed_in
    from tests.fakes import consented

    client = TestClient(app, headers=signed_in("s2"))
    consented(client)
    docs.docs["users/s2"]["formats"] = ["podcast"]
    url = "/v1/content/main/recommendations?basis=article"
    client.get(url)
    items = client.get(url).json()["items"]
    assert items and items[0]["format"] == "podcast"


# Decision 69 B1: the end-of-article list follows the article (key ideas, the same story
# elsewhere), never the reader's new terms.


def _story_recs(client, persona="newcomer", content="main"):
    url = f"/v1/content/{content}/recommendations?basis=story&persona={persona}"
    client.get(url)
    return client.get(url).json()


def test_story_basis_follows_the_article_and_never_says_new_to_you(env):
    from app.recs.feed_rank import key_ideas

    client, _, _, store = env
    ideas, _ = key_ideas(store.docs["main"], GRAPH)
    idea_ids = {c.id for c in ideas}
    for persona in ("newcomer", "trader", "policy_student"):
        items = _story_recs(client, persona)["items"]
        assert items and len(items) > 3  # a full list, not the chips' one per format
        for item in items:
            assert "new to you" not in item["why"]
            if item["relation"] in ("same_story", "angle"):
                continue  # their own reasons ("The same story, told by …")
            assert "a key idea here" in item["why"], item
            assert {t["id"] for t in item["triggers"]} <= idea_ids
        # a library primer or deeper item gets the key-idea reason too
        assert any(
            i["kind"] == "library" and i["relation"] not in ("same_story", "angle") for i in items
        )


def test_story_basis_is_the_same_ideas_for_every_persona(env):
    client, *_ = env
    a, b = (_story_recs(client, p)["items"] for p in ("newcomer", "trader"))
    ideas = [{t["id"] for i in items for t in i["triggers"]} for items in (a, b)]
    assert ideas[0] and ideas[0] & ideas[1]  # the article's ideas; formats differ per persona


def test_the_consumer_basis_is_unchanged_for_the_old_web(env):
    client, *_ = env
    get_recs(client)
    items = get_recs(client)["items"]
    assert any("new to you" in i["why"] for i in items)  # the live old web keeps its list


# Decision 69 B2: more coverage of the same story, for corpus articles only.


def _story_queries(provider, store, content="main"):
    title = ws.story_query(store.docs[content].title)
    return [q for q in provider.queries if q == title]


def test_story_items_lead_with_more_on_this_story(env):
    client, provider, calls, store = env
    first = client.get("/v1/content/main/recommendations?basis=story&persona=newcomer").json()
    assert first["pending"] is True
    items = _story_recs(client)["items"]
    lead = [i for i in items[: recs_router.STORY_LEAD] if i["relation"] == "same_story"]
    assert lead and all(i["why"] == "More on this story" and i["kind"] == "web" for i in lead)
    assert {i["format"] for i in items if i["why"] == "More on this story"} <= {"article", "video"}
    assert len(_story_queries(provider, store)) == 2  # article + video, never podcast
    assert calls.extra.get(ws.STORY) == 2  # one per format (the fake isn't YouTube's 2 units)
    assert calls.feed == 0  # never the For you feed's share
    assert calls.anonymous >= 2  # an anonymous (demo) reader's story search counts there


def test_a_story_is_searched_once_ever_even_when_empty(env, monkeypatch):
    client, provider, _, store = env
    real = provider.search

    async def nothing_for_the_story(query, fmt, news=False, include_domains=()):
        if query == ws.story_query(store.docs["main"].title):
            provider.queries.append(query)
            return []
        return await real(query, fmt, news, include_domains)

    monkeypatch.setattr(provider, "search", nothing_for_the_story)
    _story_recs(client)
    _story_recs(client, "trader")
    assert len(_story_queries(provider, store)) == 2  # stored empty: no second search


def test_pages_a_reader_brought_in_never_send_their_title(env):
    client, provider, _, store = env
    for source in ("user_ingested", "extension"):
        cid = f"own-{source}"
        store.docs[cid] = store.docs["main"].model_copy(
            update={"content_id": cid, "source": source}
        )
        read_router.reset_catalog()
        recs_router._index = None
    for source in ("user_ingested", "extension"):
        url = f"/v1/content/own-{source}/recommendations?basis=story&persona=newcomer"
        client.get(url)
        assert all(
            i["why"] != "More on this story" for i in client.get(url).json().get("items", [])
        )
    assert _story_queries(provider, store) == []


def test_a_spent_story_cap_leaves_the_key_ideas(env, monkeypatch):
    client, provider, _, store = env
    settings = config.get_settings().model_copy(update={"story_search_daily_cap": 0})
    monkeypatch.setattr(ws.get_web_search(), "_settings", settings)
    items = _story_recs(client)["items"]
    assert items and all(i["why"] != "More on this story" for i in items)
    assert _story_queries(provider, store) == []


def test_the_story_filter_drops_the_article_itself_and_unrelated_hits():
    labels, words = ["Bond yield"], ws.title_words("Bond yields jump as the Fed signals more hikes")
    hit = WebResult(url="https://news.example/a", title="Fed hikes push yields up", source="x",
                    format="article")  # fmt: skip
    other = hit.model_copy(update={"title": "Ten pasta recipes", "url": "https://food.example/b"})
    assert ws.story_relevant(hit, labels, words)
    assert not ws.story_relevant(other, labels, words)


def test_the_story_route_drops_the_articles_own_url(env, monkeypatch):
    client, provider, _, store = env
    doc = store.docs["main"]
    real = provider.search

    async def itself_first(query, fmt, news=False, include_domains=()):
        out = await real(query, fmt, news, include_domains)
        if query == ws.story_query(doc.title) and fmt == "article":
            return [out[0].model_copy(update={"url": doc.final_url or doc.url}), *out]
        return out

    monkeypatch.setattr(provider, "search", itself_first)
    urls = {i["url"] for i in _story_recs(client)["items"]}
    assert (doc.final_url or doc.url) not in urls


def test_story_items_lead_even_when_the_ranking_would_leave_them_out(env, monkeypatch):
    """Live check (2026-10-17): five stored story results, none shown, because `select` keeps
    the six best scores and a same-story item scores below a key-idea explainer. Up to
    STORY_LEAD story items are now included and lead, whatever their score."""
    client, *_ = env
    monkeypatch.setattr(recs_router, "STORY_RELEVANCE", 1e-6)  # outscored by everything else
    items = _story_recs(client)["items"]
    lead = items[: recs_router.STORY_LEAD]
    assert [i["why"] for i in lead] == ["More on this story"] * recs_router.STORY_LEAD
    assert len(items) <= 6
    assert all("a key idea here" in i["why"] for i in items[recs_router.STORY_LEAD :])
