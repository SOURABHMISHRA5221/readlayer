"""For you feed API (M7.5 §A): topic-only queries, shared cache, caps, timeout, snapshots."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import config, llm
from app.content import router as read_router
from app.graph.graph import ConceptGraph
from app.graph.loader import get_graph, set_graph
from app.graph.models import Concept, ConceptGraphFile
from app.graph.taxonomy import BY_ID, DOMAIN_IDS
from app.main import app
from app.recs import feed as feed_mod
from app.recs import feed_router
from app.recs import web_search as ws
from app.recs.models import WebResult
from app.store.content_repo import InMemoryContentStore, set_content_store
from app.store.docstore import get_doc_store
from tests.fakes import auth, consented

GRAPH = ConceptGraph(ConceptGraphFile(version="t", concepts=[
    Concept(id="c_offside", label="Offside", domain="sports", definition="A rule.",
            base_difficulty=1.0, embedding=[1.0, 0.0]),
    Concept(id="c_tariff", label="Tariff", domain="economics", definition="A tax on imports.",
            base_difficulty=1.0, embedding=[0.0, 1.0]),
]))  # fmt: skip


class TopicProvider:
    """Returns one result per query that names its topic (so it passes relevance)."""

    name = "fake"
    formats = frozenset({"article", "video", "podcast"})

    def __init__(self, delay: float = 0.0):
        self.queries: list[str] = []
        self.domains: list[tuple[str, ...]] = []
        self.delay = delay

    async def search(self, query, fmt, news=False, include_domains=()):
        self.queries.append(query)
        self.domains.append(tuple(include_domains))
        if self.delay:
            await asyncio.sleep(self.delay)
        slug = query.replace(" ", "-") + "-today"  # an article-like slug (≥ 3 words)
        host = include_domains[0] if include_domains else "x.test"  # the fallback: a wire
        return [WebResult(url=f"https://{host}/{fmt}/{slug}", title=f"{query} today",
                          source=host, format=fmt)]  # fmt: skip


def service(provider, calls=None):
    return ws.WebSearch({"article": provider, "video": provider, "podcast": provider},
                        ws.InMemoryRecCache(), calls or ws.InMemorySearchCalls(),
                        config.get_settings(), frozenset())  # fmt: skip


@pytest.fixture
def env(monkeypatch):
    set_content_store(InMemoryContentStore())
    read_router.reset_catalog()
    previous = get_graph()
    set_graph(GRAPH)
    provider = TopicProvider()
    web = service(provider)
    ws.set_web_search(web)
    feed_router.set_feed_search(feed_mod.FeedSearch(web))

    async def no_llm(*a, **k):
        raise AssertionError("the feed never calls an LLM")

    monkeypatch.setattr(llm, "run_with_meta", no_llm)
    yield provider, web
    feed_router.set_feed_search(None)
    ws.set_web_search(None)
    set_graph(previous)
    set_content_store(None)
    read_router.reset_catalog()


def google(uid, interests):
    c = TestClient(app, headers=auth(uid))
    consented(c)

    async def put():
        async def body(t):
            for d, v in interests.items():
                t.set(f"users/{uid}/domains/{d}", {"theta": 0.0, "thinks_in": 0.0, "interest": v})

        await get_doc_store().run(body)

    asyncio.run(put())
    return c


def test_queries_are_only_a_taxonomy_label_and_a_fixed_phrase():
    for d in DOMAIN_IDS:
        for fmt, phrase in feed_mod.FEED_PHRASE.items():
            assert feed_mod.feed_query(d, fmt) == f"{BY_ID[d].label} {phrase}"


def test_topics_are_the_strongest_stored_interests():
    assert feed_mod.reader_topics({"health": 1.0, "sports": 0.8, "finance": 0.3}) == [
        "health",
        "sports",
    ]  # fmt: skip  (0.3 = onboarding's "not chosen")
    assert feed_mod.reader_topics({"law": 0.3, "finance": 0.4}) == ["finance", "law"]
    assert feed_mod.reader_topics({}) == ["economics", "finance", "business", "policy"]
    many = {d: 1.0 for d in DOMAIN_IDS}
    assert len(feed_mod.reader_topics(many)) == feed_mod.MAX_TOPICS


def test_a_google_reader_gets_their_topics_and_a_second_reader_shares_the_cache(env):
    provider, _ = env
    a = google("ga", {"health": 1.0, "sports": 0.9})
    body = a.get("/v1/feed").json()
    assert body["topics"] == ["health", "sports"] and body["snapshot"] is False
    assert {i["topic"] for i in body["items"]} == {"health", "sports"}
    assert {i["format"] for i in body["items"]} == {"article", "video", "podcast"}
    assert sorted(provider.queries) == sorted(
        f"{BY_ID[t].label} {p}" for t in ("health", "sports") for p in feed_mod.FEED_PHRASE.values()
    )  # topic labels only: no reader text, no concept names
    before = len(provider.queries)
    b = google("gb", {"sports": 1.0, "health": 0.5})
    assert b.get("/v1/feed").status_code == 200
    assert len(provider.queries) == before  # same (topic, format, day): no new search


def test_the_feed_cap_holds_and_up_next_can_still_search(env, monkeypatch):
    provider, web = env
    monkeypatch.setattr(config.get_settings(), "feed_search_daily_cap", 2)
    google("gc", {d: 1.0 for d in DOMAIN_IDS[:6]}).get("/v1/feed")
    assert len(provider.queries) == 2  # the feed stopped at its own cap
    got = asyncio.run(web.fetch("c_any", "Bond yield", "article"))
    assert got and len(provider.queries) == 3  # Up next is untouched by the feed cap


def test_slow_searches_come_back_pending_and_join_the_inflight_task(env):
    slow = TopicProvider(delay=0.3)
    web = service(slow)
    search = feed_mod.FeedSearch(web)

    async def run():
        first = await search.gather(["health"], GRAPH, datetime.now(UTC), wait_s=0.05,
                                    article_topics=["health"])  # fmt: skip
        second = await search.gather(["health"], GRAPH, datetime.now(UTC), wait_s=1.0,
                                     article_topics=["health"])  # fmt: skip
        return first, second

    first, second = asyncio.run(run())
    assert first.pending is True and first.candidates == []
    assert second.pending is False and len(second.candidates) == 3
    assert len(slow.queries) == 3  # the re-ask joined the in-flight searches


def _snapshot(prepared_at):
    item = WebResult(url="https://www.bbc.co.uk/news/articles/c620r33plgppo",
                     title="Technology latest news today", source="BBC",
                     format="article", published_at=prepared_at)  # fmt: skip
    return feed_mod.Snapshot("newcomer", prepared_at, ("technology", "economics"),
                             (("technology", item),))  # fmt: skip


def test_demo_readers_get_the_snapshot_with_no_search(env):
    provider, _ = env
    old = (datetime.now(UTC) - timedelta(days=30)).isoformat()  # still served a month later
    asyncio.run(feed_mod.SnapshotRepo(get_doc_store()).put(_snapshot(old)))
    body = TestClient(app, headers=auth("demo", anonymous=True)).get(
        "/v1/feed?persona=newcomer").json()  # fmt: skip
    assert body["snapshot"] is True and body["prepared_at"] == old
    assert [i["title"] for i in body["items"]] == ["Technology latest news today"]
    assert provider.queries == []


def test_the_route_carries_readiness_for_a_demo_snapshot(env):
    """Decision 60: an item naming a map idea gets a level; one naming none gets no line."""
    now = datetime.now(UTC).isoformat()
    named = WebResult(url="https://www.bbc.co.uk/news/articles/tariffs-explained",
                      title="Tariffs explained", source="BBC", format="article",
                      published_at=now)  # fmt: skip
    snap = _snapshot(now)
    snap = feed_mod.Snapshot(snap.persona, now, snap.topics, (*snap.items, ("economics", named)))
    asyncio.run(feed_mod.SnapshotRepo(get_doc_store()).put(snap))
    body = TestClient(app, headers=auth("demo3", anonymous=True)).get(
        "/v1/feed?persona=newcomer").json()  # fmt: skip
    items = {i["title"]: i for i in body["items"]}
    assert items["Tariffs explained"]["readiness"] == "ready"  # new, no prerequisites
    assert items["Technology latest news today"]["readiness"] is None  # names no idea
    assert all(i["read_first"] == [] for i in items.values())


def test_a_missing_snapshot_is_an_empty_state(env):
    provider, _ = env
    body = TestClient(app, headers=auth("demo2", anonymous=True)).get(
        "/v1/feed?persona=trader").json()  # fmt: skip
    assert body == {"topics": ["finance", "business"], "items": [], "pending": False,
                    "snapshot": True, "prepared_at": None, "country": None}  # fmt: skip
    assert provider.queries == []


def test_feed_items_are_remembered_as_feed_relation(env):
    a = google("gd", {"sports": 1.0})
    items = a.get("/v1/feed").json()["items"]
    doc = asyncio.run(get_doc_store().get("users/gd/rec_signals/default"))
    assert {v["relation"] for v in doc["served"].values()} == {"feed"}
    assert set(doc["served"]) == {i["id"] for i in items}


def test_a_changed_phrase_makes_todays_cached_entry_stale(env):
    provider, web = env
    google("ge", {"health": 1.0}).get("/v1/feed")
    key = feed_mod.fallback_key("health", feed_mod.today_utc())
    query = feed_mod.feed_query("health", "article")
    assert asyncio.run(web.cached_entry(key, "article", query)) is not None
    assert asyncio.run(web.cached_entry(key, "article", query + " v2")) is None


def test_an_empty_day_entry_is_searched_again_once_then_stops(monkeypatch):
    class Empty(TopicProvider):
        async def search(self, query, fmt, news=False, include_domains=()):
            self.queries.append(query)
            return []

    empty = Empty()
    search = feed_mod.FeedSearch(service(empty))

    async def twice():
        for _ in range(2):
            await search.gather(["health"], GRAPH, datetime.now(UTC), wait_s=1.0,
                                article_topics=["health"])  # fmt: skip

    asyncio.run(twice())
    assert len(empty.queries) == 3  # within the hour: the empty entries are served
    monkeypatch.setattr(feed_mod, "EMPTY_RETRY", timedelta(0))
    asyncio.run(twice())
    assert len(empty.queries) == 6  # one retry each after the hour
    asyncio.run(twice())
    assert len(empty.queries) == 6  # then no more today (≤ MAX_SEARCHES per instance)


def test_a_cap_hit_serves_yesterdays_entry_and_backs_off(env, monkeypatch):
    provider, web = env
    yesterday = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d")
    old = WebResult(
        url="https://x.test/2026/10/09/health-story-from-yesterday",
        title="Health story from yesterday", source="x.test", format="article",
    )  # fmt: skip
    asyncio.run(web._cache.put(feed_mod.fallback_key("health", yesterday), "article", [old],
                               ws.cache_key(feed_mod.feed_query("health", "article"))))  # fmt: skip
    monkeypatch.setattr(config.get_settings(), "feed_search_daily_cap", 0)
    search = feed_mod.FeedSearch(web)
    got = asyncio.run(search.gather(["health"], GRAPH, datetime.now(UTC), wait_s=1.0,
                                    article_topics=["health"]))  # fmt: skip
    assert [c.result.title for c in got.candidates] == ["Health story from yesterday"]
    assert got.pending is False and provider.queries == []
    monkeypatch.setattr(config.get_settings(), "feed_search_daily_cap", 60)
    again = asyncio.run(search.gather(["health"], GRAPH, datetime.now(UTC), wait_s=1.0,
                                      article_topics=["health"]))  # fmt: skip
    assert provider.queries == [] and len(again.candidates) == 1  # backing off for 10 minutes


def test_a_learning_goal_boosts_the_feed_item_that_names_its_target(env, monkeypatch):
    """Through the routes: POST a learning goal (resolution faked, no LLM), then GET /v1/feed."""
    from app.me import goals as goals_api

    provider, _ = env

    async def fake_resolve(graph, names, threshold, **kw):
        hit = graph.lookup(names[0])
        return ({names[0].casefold(): hit.id} if hit else {}), []

    monkeypatch.setattr(goals_api, "resolve_names", fake_resolve)
    original = provider.search

    async def naming_offside(query, fmt, news=False, include_domains=()):
        results = await original(query, fmt, news, include_domains)
        if fmt == "article":
            results.append(WebResult(url="https://apnews.com/2026/10/10/offside-rule-explained",
                                     title="The offside rule, explained", source="apnews.com",
                                     format="article"))  # fmt: skip
        return results

    provider.search = naming_offside
    c = google("goalfeed", {"sports": 1.0})
    goal = c.post("/v1/me/goals", json={"type": "learning", "text": "understand offside"})
    assert goal.status_code == 200 and goal.json()["label"] == "Offside"
    items = c.get("/v1/feed").json()["items"]
    boosted = [i for i in items if i["goal"]]
    assert [i["title"] for i in boosted] == ["The offside rule, explained"]
    assert "helps your goal: Offside" in boosted[0]["why"]
    assert items[0]["title"] == "The offside rule, explained"  # ranked first


def test_not_interested_keeps_a_feed_item_away(env):
    c = google("dismisser", {"sports": 1.0})
    first = c.get("/v1/feed").json()["items"]
    gone = first[0]["id"]
    sent = c.post("/v1/recs/events", json={"events": [
        {"id": "e-dismiss-1", "type": "rec_dismissed", "item_id": gone}]})  # fmt: skip
    assert sent.status_code == 200
    again = c.get("/v1/feed").json()["items"]
    assert gone not in {i["id"] for i in again} and len(again) == len(first) - 1
