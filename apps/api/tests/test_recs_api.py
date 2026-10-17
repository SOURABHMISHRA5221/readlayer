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
    rest = items[recs_router.STORY_LEAD :]
    assert all(
        "a key idea here" in i["why"] or i["relation"] in ("same_story", "angle") for i in rest
    )


def test_the_story_list_spreads_over_the_articles_ideas(env, monkeypatch):
    """Sourabh, 2026-10-17 (a strangulation-law article): "the bottom articles still focusing on
    single word": with three results per idea the top idea took every slot. Each idea's n-th
    item now counts SPREAD**n, so the next ideas get places (no new searches)."""
    from collections import Counter

    from app.recs.feed_rank import key_ideas

    client, provider, _, store = env
    real = provider.search

    async def three_each(query, fmt, news=False, include_domains=()):
        one = (await real(query, fmt, news, include_domains))[0]
        return [one.model_copy(update={"url": f"{one.url}-{i}"}) for i in range(3)]

    monkeypatch.setattr(provider, "search", three_each)
    monkeypatch.setattr(recs_router, "STORY_FORMATS", ())  # like a page a reader brought in
    ideas, _ = key_ideas(store.docs["main"], GRAPH)
    assert len(ideas) >= 2
    items = _story_recs(client)["items"]
    per_idea = Counter(
        i["triggers"][0]["id"] for i in items if i["relation"] != "same_story" and i["triggers"]
    )
    assert len(per_idea) >= 2, per_idea  # more than one of the article's ideas
    assert max(per_idea.values()) <= 2, per_idea


def test_a_dismissed_story_item_stays_gone(env, monkeypatch):
    """milestone-reviewer: `_lead_with_story` added story items without the reader's signals, so
    a dismissed (or finished) "More on this story" card came back on the next load."""
    client, *_ = env
    monkeypatch.setattr(recs_router, "STORY_RELEVANCE", 1e-6)  # forces the lead path
    first = _story_recs(client)["items"]
    story = [i for i in first if i["why"] == "More on this story"]
    assert story
    resp = client.post("/v1/recs/events", json={"persona": "newcomer", "events": [
        {"id": "d1", "type": "rec_dismissed", "item_id": story[0]["id"]}]})  # fmt: skip
    assert resp.json()["applied"] == 1
    after = client.get("/v1/content/main/recommendations?basis=story&persona=newcomer").json()
    assert story[0]["id"] not in [i["id"] for i in after["items"]]


def test_spread_halves_each_ideas_next_item_and_the_cap_reranks():
    from app.recs.rank import Candidate

    def k(i):
        return (i, "explainer")

    got = recs_router._spread([(k("a1"), "x", 1.0), (k("a2"), "x", 0.9), (k("a3"), "x", 0.8),
                               (k("b1"), "y", 0.7), (k("n"), None, 0.6)])  # fmt: skip
    assert got == {k("a1"): 1.0, k("a2"): 0.45, k("a3"): 0.2, k("b1"): 0.7, k("n"): 0.6}

    cands = [Candidate(i, "explainer", "article", 1.0) for i in ("a1", "a2", "a3", "b1")]
    idea = {k("a1"): "x", k("a2"): "x", k("a3"): "x", k("b1"): "y"}
    ranked = {"a1": 0.9, "a2": 0.8, "a3": 0.7, "b1": 0.1}

    def reselect(cs):
        return sorted(((c, ranked[c.id]) for c in cs), key=lambda cs: -cs[1])[:3]

    out = recs_router._cap_per_idea(reselect(cands), cands, idea, reselect)
    assert [c.id for c, _ in out] == ["a1", "a2", "b1"]  # a3 set aside, idea y takes its place


def _top(n, scores):
    def reselect(cs):
        return sorted(((c, scores[c.id]) for c in cs), key=lambda cs: (-cs[1], cs[0].id))[:n]

    return reselect


def test_the_cap_never_shrinks_the_list():
    """plan-reviewer: one linked idea (a pasted page has no story items) must keep its list."""
    from app.recs.rank import Candidate

    only_x = [Candidate(f"x{i}", "explainer", "article", 1.0) for i in range(4)]
    idea = {(c.id, "explainer"): "x" for c in only_x}
    pick = _top(6, {c.id: 1.0 - i / 10 for i, c in enumerate(only_x)})
    assert len(recs_router._cap_per_idea(pick(only_x), only_x, idea, pick)) == 4

    mixed = [*(Candidate(f"x{i}", "explainer", "article", 1.0) for i in range(5)),
             Candidate("y0", "explainer", "video", 1.0)]  # fmt: skip
    idea = {(c.id, "explainer"): c.id[0] for c in mixed}
    pick = _top(6, {**{f"x{i}": 1.0 - i / 10 for i in range(5)}, "y0": 0.05})
    out = recs_router._cap_per_idea(pick(mixed), mixed, idea, pick)
    assert len(out) == 6 and "y0" in {c.id for c, _ in out}


def test_ideas_are_counted_per_relation_and_same_story_follows_none():
    from app.recs.library import LibraryCandidate

    lib = [LibraryCandidate("d1", "primer", 0.9, ("c_a",)),
           LibraryCandidate("d1", "angle", 0.8, ("c_b",)),
           LibraryCandidate("d2", "same_story", 0.7, ("c_a",))]  # fmt: skip
    items = recs_router._idea_items(lib, {})
    idea = {key: i for key, i, _ in items}
    assert idea[("lib:d1", "primer")] == "c_a" and idea[("lib:d1", "angle")] == "c_b"
    assert idea[("lib:d2", "same_story")] is None
    weight = recs_router._spread(items + [(("web:e1", "explainer"), "c_a", 1.0),
                                          (("web:e2", "explainer"), "c_a", 0.95)])  # fmt: skip
    assert weight[("lib:d2", "same_story")] == 0.7  # never halved behind c_a's explainers
