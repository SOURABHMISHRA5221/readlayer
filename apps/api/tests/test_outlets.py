"""Decision 50: outlet registry, feed parsing, the collection job and its endpoint, the 60/40
mix, the restricted search fallback, and the reader's country."""
# ruff: noqa: F811  (tests take the shared feed `env` fixture imported from test_feed_api)

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient

from app import config
from app.graph.graph import ConceptGraph
from app.graph.models import ConceptGraphFile
from app.graph.taxonomy import DOMAIN_IDS
from app.ingest.safe_fetch import FetchedPage, FetchError
from app.main import app
from app.recs import feed as feed_mod
from app.recs import feed_rank as fr
from app.recs import internal_router, outlet_feed, outlet_job
from app.recs import web_search as ws
from app.recs.models import WebResult
from app.recs.outlets import (
    BY_OUTLET,
    REGISTRY,
    WIRE_HOSTS,
    eligible,
    fallback_domains,
    feed_urls,
    side_of,
)
from app.store.docstore import get_doc_store
from app.store.outlet_repo import OutletList, OutletStore, outlets_path
from tests.fakes import auth, consented
from tests.test_feed_api import env, google  # noqa: F401  (fixture)

FEEDS = Path(__file__).parent / "fixtures" / "feeds"
NOW = datetime(2026, 10, 11, 18, 0, tzinfo=UTC)  # the fixtures were saved then


def fixture(name: str) -> bytes:
    return (FEEDS / f"{name}.xml").read_bytes()


# ---------------------------------------------------------------- registry


def test_every_topic_has_a_global_and_an_indian_section():
    for topic in DOMAIN_IDS:
        regions = {o.region for o in REGISTRY if topic in o.sections}
        assert regions == {"global", "IN"}, topic


def test_feed_and_article_hosts_are_the_outlets_own_and_https():
    for o in REGISTRY:
        assert o.feed_hosts and o.article_hosts
        for urls in o.sections.values():
            for url in urls:
                parts = urlsplit(url)
                assert parts.scheme == "https", url
                assert outlet_feed.on_hosts(url, o.feed_hosts), url
    assert BY_OUTLET["bbc"].feed_hosts == ("feeds.bbci.co.uk",)
    assert set(BY_OUTLET["bbc"].article_hosts) == {"bbc.co.uk", "bbc.com"}
    assert len(feed_urls()) == len(set(feed_urls()))


def test_sides_by_country():
    bbc, npr, hindu = BY_OUTLET["bbc"], BY_OUTLET["npr"], BY_OUTLET["hindu"]
    assert [eligible(o, "IN") for o in (bbc, npr, hindu)] == ["global", "global", "local"]
    assert [eligible(o, "GB") for o in (bbc, npr, hindu)] == ["local", "global", None]
    assert [eligible(o, "US") for o in (bbc, npr, hindu)] == ["global", "local", None]
    for country in (None, "other"):
        assert [eligible(o, country) for o in (bbc, npr, hindu)] == ["global", "global", None]
    assert side_of("www.reuters.com", "IN") == "global"
    assert side_of("www.thehindu.com", "IN") == "local"
    assert side_of("smalltown-gazette.com", "IN") is None


def test_fallback_domains_are_one_constant_list():
    domains = fallback_domains()
    assert domains == sorted(domains) and set(WIRE_HOSTS) <= set(domains)
    assert {h for o in REGISTRY for h in o.article_hosts} <= set(domains)


# ---------------------------------------------------------------- parsing


@pytest.mark.parametrize(
    ("name", "outlet", "kept"),
    [("bbc_business", "bbc", 5), ("guardian_economics", "guardian", 5),
     ("hindu_business", "hindu", 5), ("mint_economy", "mint", 5),
     ("guardian_sport", "guardian", 3)],  # the sport fixture holds 2 live blogs
)  # fmt: skip
def test_saved_feeds_parse_to_fresh_articles(name, outlet, kept):
    entries = outlet_feed.parse_entries(fixture(name))
    topic = {"business": "business", "economics": "economics", "economy": "economics",
             "sport": "sports"}[name.split("_")[1]]  # fmt: skip
    items = outlet_feed.outlet_items(BY_OUTLET[outlet], entries, NOW, topic)
    assert len(entries) == 5 and len(items) == kept
    for r in items:
        assert r.format == "article" and r.source == BY_OUTLET[outlet].name
        assert "?" not in r.url and "#" not in r.url and "/live/" not in r.url
        assert "<" not in r.snippet and r.published_at and r.title
    assert any(r.thumbnail for r in items)


def test_parse_only_takes_bytes():
    with pytest.raises(TypeError):
        outlet_feed.parse_entries("https://feeds.bbci.co.uk/news/business/rss.xml")  # type: ignore[arg-type]


def rss(*items: str) -> bytes:
    return ('<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>'
            + "".join(items) + "</channel></rss>").encode()  # fmt: skip


def item(link: str, title: str = "A story about rates", when: datetime = NOW, desc: str = ""):
    stamp = when.strftime("%a, %d %b %Y %H:%M:%S GMT")
    return (f"<item><title>{title}</title><link>{link}</link><pubDate>{stamp}</pubDate>"
            f"<description>{desc}</description></item>")  # fmt: skip


def test_media_old_foreign_and_undated_items_are_dropped():
    body = rss(
        item("https://www.bbc.co.uk/news/articles/c111"),
        item("https://www.bbc.co.uk/news/av/business-123"),  # video
        item("https://www.bbc.co.uk/sounds/audio/p0abc"),  # audio
        item("https://www.bbc.co.uk/news/articles/c222", when=NOW - timedelta(days=4)),
        item("https://evil.example/news/articles/c333"),  # not the outlet's host
        item("https://www.bbc.co.uk/news/articles/c444", title="Новости рынка сегодня"),
        "<item><title>Undated</title><link>https://www.bbc.co.uk/news/articles/c555</link></item>",
    )
    items = outlet_feed.outlet_items(
        BY_OUTLET["bbc"], outlet_feed.parse_entries(body), NOW, "business"
    )
    assert [r.url for r in items] == ["https://www.bbc.co.uk/news/articles/c111"]


def test_descriptions_are_stripped_then_unescaped():
    desc = "&lt;p&gt;Rates &amp;amp; &lt;b&gt;bonds&lt;/b&gt;&lt;/p&gt; &amp;lt;script&amp;gt;"
    body = rss(item("https://www.bbc.co.uk/news/articles/c1", desc=desc))
    (entry,) = outlet_feed.parse_entries(body)
    assert entry.summary == "Rates & bonds <script>"  # an escaped tag stays visible text


def test_one_story_in_two_sections_is_kept_once_and_old_items_leave_on_merge():
    def parsed(link):
        entries = outlet_feed.parse_entries(rss(item(link)))
        return outlet_feed.outlet_items(BY_OUTLET["bbc"], entries, NOW, "business")

    a = parsed("https://www.bbc.co.uk/news/articles/c1?at_medium=RSS&amp;at_campaign=rss")
    b = parsed("https://www.bbc.co.uk/news/articles/c1#comments")
    merged = outlet_feed.merge(a, b, NOW)
    assert [r.url for r in merged] == ["https://www.bbc.co.uk/news/articles/c1"]
    assert outlet_feed.merge(merged, [], NOW + timedelta(days=4)) == []


def test_non_news_sections_stay_out_of_news_topics():
    body = rss(
        item("https://www.theguardian.com/world/2026/oct/14/student-protests-tirana"),
        item("https://www.theguardian.com/stage/2026/oct/15/paddington-the-musical-sydney"),
        item("https://www.theguardian.com/sport/2026/oct/15/england-squad-named"),
    )
    entries = outlet_feed.parse_entries(body)

    def kept(topic):
        items = outlet_feed.outlet_items(BY_OUTLET["guardian"], entries, NOW, topic)
        return [urlsplit(r.url).path.split("/")[1] for r in items]

    assert kept("politics") == ["world"]
    assert kept("culture") == ["world", "stage"]
    assert kept("sports") == ["world", "sport"]


def test_stored_items_are_filtered_again_when_read():
    def stored(url, title="A story"):
        return WebResult(url=url, title=title, source="The Guardian", format="article")

    lists = {"politics": [OutletList("guardian", (
        stored("https://www.theguardian.com/world/2026/oct/14/student-protests-tirana"),
        stored("https://www.theguardian.com/stage/2026/oct/15/paddington-the-musical-sydney"),
        stored("https://www.theguardian.com/world/2026/oct/15/rally", "ഈ റാലി സൂചനയോ| Analysis"),
    ), NOW.isoformat())]}  # fmt: skip
    graph = ConceptGraph(ConceptGraphFile(version="t", concepts=[]))
    got = feed_mod.outlet_candidates(lists, "IN", graph)["politics"]
    assert [c.result.url.rsplit("/", 1)[1] for c in got] == ["student-protests-tirana"]


# ---------------------------------------------------------------- the job


class FakeFetcher:
    """BBC business and Guardian economics answer from fixtures; every other feed fails."""

    def __init__(self, fail: frozenset[str] = frozenset()) -> None:
        self.fail = fail
        self.calls: list[tuple[str, frozenset[str]]] = []
        self.map = {
            "https://feeds.bbci.co.uk/news/business/rss.xml": fixture("bbc_business"),
            "https://www.theguardian.com/business/economics/rss": fixture("guardian_economics"),
            "https://www.thehindu.com/business/Economy/feeder/default.rss": fixture(
                "hindu_business"
            ),
        }

    async def fetch(self, url, *, content_types=frozenset()):
        self.calls.append((url, content_types))
        if url in self.fail or url not in self.map:
            raise FetchError("not_found", "no", 404)
        return FetchedPage(url, self.map[url], "utf-8")


def test_collect_fetches_each_feed_once_with_feed_types_and_writes_one_doc_per_topic(docs):
    fetcher = FakeFetcher()
    report = asyncio.run(outlet_job.collect(fetcher, OutletStore(docs), NOW))
    urls = [u for u, _ in fetcher.calls]
    assert sorted(urls) == sorted(feed_urls()) and len(urls) == len(set(urls))
    assert all(types == outlet_feed.FEED_TYPES for _, types in fetcher.calls)
    assert {p for p in docs.written if p.startswith("rec_cache/")} == {
        outlets_path(t) for t in DOMAIN_IDS
    }  # 14 writes
    assert report.stored["economics"] == {"guardian": 5, "hindu": 5}
    assert report.stored["business"] == {"bbc": 5}
    assert report.stored["finance"] == {"bbc": 5}  # BBC's business feed also serves finance
    assert report.feeds_ok == 3


def test_a_failing_outlet_keeps_its_previous_list(docs):
    store = OutletStore(docs)
    asyncio.run(outlet_job.collect(FakeFetcher(), store, NOW))
    guardian = "https://www.theguardian.com/business/economics/rss"
    later = NOW + timedelta(hours=12)
    asyncio.run(outlet_job.collect(FakeFetcher(fail=frozenset({guardian})), store, later))
    doc = docs.docs[outlets_path("economics")]
    assert len(doc["guardian"]["items"]) >= 4  # previous run's items, still ≤ 3 days old
    assert doc["guardian"]["fetched_at"] == NOW.isoformat(timespec="seconds")
    assert doc["hindu"]["fetched_at"] == later.isoformat(timespec="seconds")


def test_feedparser_only_ever_receives_bytes(docs, monkeypatch):
    seen = []
    real = outlet_feed.feedparser.parse

    def spy(arg, *a, **k):
        seen.append(type(arg))
        return real(arg, *a, **k)

    monkeypatch.setattr(outlet_feed.feedparser, "parse", spy)
    asyncio.run(outlet_job.collect(FakeFetcher(), OutletStore(docs), NOW))
    assert seen and set(seen) == {bytes}


# ---------------------------------------------------------------- the endpoint

SA = "feed-job@readlayer-test.iam.gserviceaccount.com"
AUD = "https://api.readlayer.test/v1/internal/feeds/collect"
GOOD = {"iss": "https://accounts.google.com", "aud": AUD, "email": SA, "email_verified": True}


@pytest.fixture
def job(monkeypatch):
    settings = config.get_settings()
    monkeypatch.setattr(settings, "feed_job_sa_email", SA)
    monkeypatch.setattr(settings, "feed_job_audience", AUD)
    claims = {"value": dict(GOOD)}

    def verify(token, audience):
        if token != "good":
            raise ValueError("bad signature")
        assert audience == AUD
        return claims["value"]

    internal_router.set_verifier(verify)
    monkeypatch.setattr(internal_router, "SafeFetcher", FakeFetcher)
    monkeypatch.setattr(internal_router, "now_utc", lambda: NOW)
    yield claims
    internal_router.set_verifier(None)


PATH = "/v1/internal/feeds/collect"


def test_collect_needs_the_schedulers_token(job, docs):
    c = TestClient(app)
    assert c.post(PATH).status_code == 403
    assert c.post(PATH, headers={"Authorization": "Bearer forged"}).status_code == 403
    # A Firebase ID token (what readers send) never passes: signature/issuer/audience differ.
    assert c.post(PATH, headers=auth("reader")).status_code == 403
    wrong = [{"email": "other@x.iam.gserviceaccount.com"}, {"aud": "https://other/"},
             {"iss": "https://securetoken.google.com/x"}, {"email_verified": False}]  # fmt: skip
    for bad in wrong:
        job["value"] = GOOD | bad
        assert c.post(PATH, headers={"Authorization": "Bearer good"}).status_code == 403, bad
    assert not any(p.startswith("rec_cache/") for p in docs.written)
    job["value"] = dict(GOOD)
    ok = c.post(PATH, headers={"Authorization": "Bearer good"})
    assert ok.status_code == 200 and ok.json()["stored"]["economics"]["guardian"] == 5
    assert outlets_path("economics") in docs.written


@pytest.mark.parametrize("missing", ["feed_job_sa_email", "feed_job_audience"])
def test_collect_fails_closed_without_its_settings(job, monkeypatch, missing):
    monkeypatch.setattr(config.get_settings(), missing, "")
    resp = TestClient(app).post(PATH, headers={"Authorization": "Bearer good"})
    assert resp.status_code == 403


# ---------------------------------------------------------------- the mix


def test_article_split_holds_sixty_forty_and_backfills():
    assert fr.article_split([(5, 5)] * 3, 3, 0.6) == [(2, 1), (2, 1), (1, 2)]  # 5 of 9 local
    assert fr.article_split([(1, 5), (0, 5), (0, 5)], 3, 0.6) == [(1, 2), (0, 3), (0, 3)]
    assert fr.article_split([(5, 0), (5, 1)], 3, 0.6) == [(3, 0), (2, 1)]  # short global
    assert fr.article_split([(0, 5)] * 2, 3, 0.6) == [(0, 3), (0, 3)]  # no local supply
    for pools in ([(2, 9), (9, 0), (3, 3)], [(4, 4)] * 4, [(1, 1), (6, 6)]):
        split = fr.article_split(pools, 3, 0.6)
        total = sum(a + b for a, b in split)
        local = sum(a for a, _ in split)
        assert all(a <= p[0] and b <= p[1] for (a, b), p in zip(split, pools, strict=True))
        assert abs(local - 0.6 * total) <= 1


def store_outlets(topics, per_outlet=3, only=None):
    """Fresh outlet entries for these topics: `per_outlet` items per (outlet, topic)."""
    now = datetime.now(UTC)
    store = OutletStore(get_doc_store())
    for topic in topics:
        fresh = {}
        for o in REGISTRY:
            if topic not in o.sections or (only and o.id not in only):
                continue
            host = o.article_hosts[0]
            fresh[o.id] = [
                WebResult(url=f"https://www.{host}/{topic}/2026/story-{o.id}-{i}",
                          title=f"{o.name} {topic} story {i}", source=o.name, format="article",
                          published_at=(now - timedelta(hours=i + 1)).isoformat())
                for i in range(per_outlet)
            ]  # fmt: skip
        asyncio.run(store.merge_topic(topic, fresh, now))


def articles(body):
    return [i for i in body["items"] if i["format"] == "article"]


def with_country(c, country):
    assert c.patch("/v1/me/settings", json={"country": country}).status_code == 200
    return c


def test_an_indian_reader_gets_sixty_forty_from_registry_outlets(env):
    provider, _ = env
    topics = {"economics": 1.0, "politics": 0.9, "sports": 0.8}
    store_outlets(topics)
    body = with_country(google("in1", topics), "IN").get("/v1/feed").json()
    arts = articles(body)
    sides = [side_of(urlsplit(a["url"]).hostname or "", "IN") for a in arts]
    assert len(arts) == 9 and None not in sides
    assert abs(sides.count("local") - 0.6 * len(arts)) <= 1
    assert body["country"] == "IN"
    assert not [q for q in provider.queries if "news this week" in q]  # no article search


def test_no_country_means_global_outlets_only_and_gb_local_is_bbc_and_guardian(env):
    topics = {"economics": 1.0, "technology": 0.9}
    store_outlets(topics)
    plain = google("none1", topics).get("/v1/feed").json()
    hosts = {urlsplit(a["url"]).hostname for a in articles(plain)}
    assert hosts and all(side_of(h or "", None) == "global" for h in hosts)
    assert plain["country"] is None
    gb = with_country(google("gb1", topics), "GB").get("/v1/feed").json()
    gb_sides = [side_of(urlsplit(a["url"]).hostname or "", "GB") for a in articles(gb)]
    assert None not in gb_sides and gb_sides.count("local") >= gb_sides.count("global")
    assert not [a for a in articles(gb) if "thehindu" in a["url"] or "livemint" in a["url"]]


def test_short_local_supply_is_backfilled_from_global(env):
    topics = {"economics": 1.0, "technology": 0.9}
    store_outlets(topics, per_outlet=3, only={"bbc", "guardian", "npr"})
    body = with_country(google("in2", topics), "IN").get("/v1/feed").json()
    assert len(articles(body)) == 6  # all global, still full


def test_before_the_first_run_the_feed_falls_back_without_an_error(env):
    provider, _ = env
    resp = google("early", {"health": 1.0}).get("/v1/feed")
    assert resp.status_code == 200
    assert "Health news this week" in provider.queries  # the restricted fallback
    assert ("Health news this week" in provider.queries) and any(provider.domains)
    assert all(urlsplit(a["url"]).hostname in WIRE_HOSTS or side_of(
        urlsplit(a["url"]).hostname or "", None) for a in articles(resp.json()))  # fmt: skip


# ---------------------------------------------------------------- fallback and country


class Capture:
    def __init__(self) -> None:
        self.bodies: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.bodies.append(request.content.decode())
        return httpx.Response(200, json={"results": [
            {"url": "https://apnews.com/article/economy-rates-story-today",
             "title": "Economy story", "content": "Inflation and rates"},
            {"url": "https://www.thehindu.com/business/rates-story-today/article70012345.ece",
             "title": "Economy story from India", "content": "Inflation and rates"},
        ]})  # fmt: skip


def tavily_service(capture: Capture) -> ws.WebSearch:
    transport = httpx.MockTransport(capture.handler)
    tavily = ws.TavilyProvider("k", frozenset(), 5.0, transport=transport)
    return ws.WebSearch({"article": tavily}, ws.InMemoryRecCache(), ws.InMemorySearchCalls(),
                        config.get_settings(), frozenset())  # fmt: skip


def test_the_fallback_restricts_to_top_outlets_and_never_excludes():
    capture = Capture()
    web = tavily_service(capture)
    results = asyncio.run(web._providers["article"].search(
        "Economics news this week", "article", news=True,
        include_domains=feed_mod.FALLBACK_DOMAINS))  # fmt: skip
    body = json.loads(capture.bodies[0])
    assert body["include_domains"] == list(feed_mod.FALLBACK_DOMAINS)
    assert "exclude_domains" not in body
    assert len(results) == 2


def test_readers_differing_only_in_country_send_identical_searches(env):
    from app.recs import feed_router

    seen = []
    for country in ("IN", "GB", None):
        capture = Capture()
        web = tavily_service(capture)
        ws.set_web_search(web)
        feed_router.set_feed_search(feed_mod.FeedSearch(web))
        c = google(f"c-{country}", {"economics": 1.0})
        if country:
            with_country(c, country)
        body = c.get("/v1/feed").json()
        seen.append((capture.bodies, sorted(web._cache.entries)))
        hosts = {urlsplit(a["url"]).hostname for a in articles(body)}
        assert ("www.thehindu.com" in hosts) == (country == "IN")  # dropped after the search
    assert seen[0] == seen[1] == seen[2] and seen[0][0]
    assert all("IN" not in b and "GB" not in b for b in seen[0][0])


def test_country_is_validated_stored_by_onboarding_exported_and_deleted(env, docs):
    c = google("cty", {"economics": 1.0})
    assert c.patch("/v1/me/settings", json={"country": "FR"}).status_code == 422
    body = {"field": "software", "interests": ["economics"], "thinks_in": ["software"],
            "country": "IN"}  # fmt: skip
    assert c.post("/v1/onboarding", json=body).status_code == 200
    assert docs.docs["users/cty"]["country"] == "IN"
    assert c.get("/v1/me/profile").json()["settings"]["country"] == "IN"
    assert c.get("/v1/me/export").json()["user"]["country"] == "IN"
    assert c.delete("/v1/me").status_code == 204
    assert "users/cty" not in docs.docs


def test_demo_readers_never_store_a_country(env):
    demo = TestClient(app, headers=auth("demo-c", anonymous=True))
    assert demo.patch("/v1/me/settings", json={"country": "IN"}).status_code == 403
    assert demo.get("/v1/me/profile?persona=newcomer").json()["settings"]["country"] is None


def test_discover_uses_outlet_entries_for_topics(env):
    provider, _ = env
    store_outlets({"economics": 1.0})
    c = consented(TestClient(app, headers=auth("disc")))
    onboard = {"field": "software", "interests": ["economics"], "thinks_in": ["software"],
               "country": "IN"}  # fmt: skip
    assert c.post("/v1/onboarding", json=onboard).status_code == 200
    items = c.post("/v1/onboarding/discover", json={"topics": ["economics"]}).json()["items"]
    assert any(side_of(urlsplit(i["url"]).hostname or "", "IN") == "local" for i in items)
    assert "Economics news this week" not in provider.queries  # no article search needed


def test_demo_snapshots_take_local_global_local_and_yield_when_a_side_runs_out():
    from scripts.seed_demo_feed import mixed

    def cand(host, i):
        r = WebResult(url=f"https://www.{host}/news/2026/story-{i}", title=f"s{i}", source=host,
                      format="article", published_at=f"2026-10-11T0{i}:00:00+00:00")  # fmt: skip
        return fr.FeedCandidate(r, "economics")

    pool = [cand("thehindu.com", i) for i in range(1, 5)] + [cand("bbc.co.uk", 5)]
    hosts = [urlsplit(r.url).hostname for r in mixed(pool)]
    assert hosts == ["www.thehindu.com", "www.bbc.co.uk", "www.thehindu.com",
                     "www.thehindu.com", "www.thehindu.com"]  # fmt: skip


def test_six_topics_keep_the_mix_through_the_24_item_cut():
    import random

    from app.recs.outlets import side_of as host_side

    rng = random.Random(7)
    topics = ["economics", "politics", "sports", "business", "technology", "health"]
    for trial in range(10):
        ranked = []
        for t in topics:
            for i in range(5):
                for host, scale in (("www.thehindu.com", 0.3 if trial % 2 else 1.0),
                                    ("www.bbc.co.uk", 1.0)):  # fmt: skip
                    r = WebResult(url=f"https://{host}/{t}/{trial}/story-{i}", title="t",
                                  source=host, format="article")  # fmt: skip
                    ranked.append(fr.RankedItem(fr.FeedCandidate(r, t), rng.random() * scale,
                                                (), None, ""))  # fmt: skip
            for fmt, n in (("video", 2), ("podcast", 1)):
                for i in range(n):
                    r = WebResult(url=f"https://www.youtube.com/{t}/{fmt}/{trial}/{i}", title="v",
                                  source="yt", format=fmt)  # fmt: skip
                    ranked.append(fr.RankedItem(fr.FeedCandidate(r, t), rng.random() * 2, (),
                                                None, ""))  # fmt: skip
        side = feed_mod.side_for("IN")
        out = fr.select(ranked, topics, side, 0.6)
        sides = [side(r.candidate) for r in out if r.candidate.result.format == "article"]
        assert len(out) <= fr.MAX_ITEMS and sides
        assert abs(sides.count("local") - 0.6 * len(sides)) <= 1, (trial, sides)
        assert host_side("www.thehindu.com", "IN") == "local"
