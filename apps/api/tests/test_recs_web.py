import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.config import Settings
from app.recs import web_search as ws
from app.recs.models import WebResult

BLOCK = frozenset({"quora.com", "spam.example"})


def settings(**kw) -> Settings:
    return Settings(_env_file=None, **({"search_daily_cap": 300} | kw))


class Recorder:
    """httpx transport that records every outgoing request and answers like the provider."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.host == "api.tavily.com":
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "url": "https://good.example/a",
                            "title": "Repo rate explained",
                            "content": "The repo rate is …",
                            "published_date": "2026-09-30",
                            "images": [{"url": "https://good.example/a.jpg"}],
                        },
                        {"url": "https://www.quora.com/q", "title": "Q", "content": "spam"},
                        {"url": "https://sub.spam.example/x", "title": "S", "content": "spam"},
                        {"url": "javascript:alert(1)", "title": "bad", "content": ""},
                    ]
                },
            )
        if request.url.path.endswith("/search"):
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": {"videoId": "abc"},
                            "snippet": {
                                "title": "Repo rate in 5 minutes",
                                "channelTitle": "Econ Explained",
                                "publishedAt": "2026-08-01T00:00:00Z",
                                "description": "d",
                                "thumbnails": {
                                    "medium": {"url": "https://i.ytimg.com/vi/abc/mq.jpg"}
                                },
                            },
                        }
                    ]
                },
            )
        return httpx.Response(
            200, json={"items": [{"id": "abc", "contentDetails": {"duration": "PT5M30S"}}]}
        )


def service(recorder, cfg=None, calls=None, cache=None):
    transport = httpx.MockTransport(recorder)
    tavily = ws.TavilyProvider("tvly-test", BLOCK, 5, transport)
    youtube = ws.YouTubeProvider("yt-test", 5, transport)
    return ws.WebSearch(
        {"article": tavily, "podcast": tavily, "video": youtube},
        cache or ws.InMemoryRecCache(),
        calls or ws.InMemorySearchCalls(),
        cfg or settings(),
        BLOCK,
    )


def test_mentions_gate():
    assert ws.mentions("Bond yield", "Yields explained in 5 minutes")
    assert ws.mentions("NPAs", "What are NPA ratios?")
    assert not ws.mentions("Singleness of money", "A Single Serving Podcast")
    assert not ws.mentions("Separation principle", "Fuel oil purifier explained")


def test_build_query_is_label_domain_and_suffix_only():
    assert ws.build_query("Repo rate", "article", "policy") == "Repo rate policy explained"
    assert ws.build_query("Repo rate", "article", "not a domain!") == "Repo rate explained"
    assert ws.build_query("Repo rate", "article") == "Repo rate explained"
    assert ws.build_query("Repo rate", "podcast") == "Repo rate podcast episode"
    assert ws.build_query('  "NPAs"\n<script>', "video") == "NPAs script explained"
    assert len(ws.build_query("x" * 500, "article")) == 80 + len(" explained")


async def test_outgoing_requests_carry_no_user_data():
    rec = Recorder()
    svc = service(rec)
    for fmt in ("article", "video", "podcast"):
        await svc.fetch("c_repo_rate", "Repo rate", fmt)
    tavily = [json.loads(r.content) for r in rec.requests if r.url.host == "api.tavily.com"]
    assert {t["query"] for t in tavily} == {"Repo rate explained", "Repo rate podcast episode"}
    yt = [r for r in rec.requests if "/youtube/" in r.url.path]
    assert yt[0].url.params["q"] == "Repo rate explained"
    forbidden = ("dev-local", "newcomer", "trader", "policy", "uid", "persona", "content_id")
    for r in rec.requests:
        text = (str(r.url) + r.content.decode() + json.dumps(dict(r.headers))).lower()
        assert not any(f in text for f in forbidden), r.url
        assert "cookie" not in {k.lower() for k in r.headers}
    podcast = next(t for t in tavily if t["query"].endswith("podcast episode"))
    assert "podcasts.apple.com" in podcast["include_domains"]


async def test_blocklist_and_bad_urls_are_dropped_and_excluded_upstream():
    rec = Recorder()
    results = await service(rec).fetch("c_repo_rate", "Repo rate", "article")
    assert [r.url for r in results] == ["https://good.example/a"]
    assert results[0].thumbnail == "https://good.example/a.jpg"
    body = json.loads(rec.requests[0].content)
    assert "quora.com" in body["exclude_domains"] and "youtube.com" in body["exclude_domains"]
    assert ws.is_blocked("https://m.quora.com/x", BLOCK) and not ws.is_blocked(
        "https://notquora.com", BLOCK
    )
    assert ws.load_blocklist()  # the committed file parses


async def test_youtube_results_are_normalized_with_duration():
    (video,) = await service(Recorder()).fetch("c_repo_rate", "Repo rate", "video")
    assert video == WebResult(
        url="https://www.youtube.com/watch?v=abc",
        title="Repo rate in 5 minutes",
        source="Econ Explained",
        format="video",
        duration_or_read_time=330,
        snippet="d",
        thumbnail="https://i.ytimg.com/vi/abc/mq.jpg",
        published_at="2026-08-01T00:00:00Z",
    )
    assert ws.parse_iso_duration("PT1H2M3S") == 3723 and ws.parse_iso_duration("P0D") is None


@pytest.mark.parametrize(
    ("languages", "kept"),
    [({"defaultAudioLanguage": "ml"}, False), ({"defaultAudioLanguage": "hi"}, False),
     ({"defaultAudioLanguage": "en-GB"}, True), ({"defaultLanguage": "hi"}, False),
     ({"defaultAudioLanguage": "en", "defaultLanguage": "hi"}, True), ({}, True)],
)  # fmt: skip
async def test_videos_spoken_in_another_language_are_dropped(languages, kept):
    def answer(request):
        if request.url.path.endswith("/videos"):
            assert request.url.params["part"] == "snippet,contentDetails"
            return httpx.Response(200, json={"items": [
                {"id": "abc", "snippet": languages, "contentDetails": {"duration": "PT5M"}}
            ]})  # fmt: skip
        return Recorder()(request)

    yt = ws.YouTubeProvider("yt-test", 5, httpx.MockTransport(answer))
    assert bool(await yt.search("Economics news explained", "video", news=True)) is kept


async def test_feed_videos_ask_for_recent_medium_length_explainers_and_up_next_does_not():
    rec = Recorder()
    yt = ws.YouTubeProvider("yt-test", 5, httpx.MockTransport(rec))
    await yt.search("Health news explained", "video", news=True)
    feed = rec.requests[0].url.params
    assert feed["videoDuration"] == "medium" and feed["publishedAfter"].endswith("Z")
    assert feed["q"] == "Health news explained"
    rec.requests.clear()
    await yt.search("Repo rate economics explained", "video")
    assert "videoDuration" not in rec.requests[0].url.params
    assert "publishedAfter" not in rec.requests[0].url.params


async def test_feed_articles_filter_other_formats_locally_instead_of_exclude_domains():
    def answer(request):
        return httpx.Response(200, json={"results": [
            {"url": "https://www.youtube.com/watch?v=x", "title": "v", "content": "c"},
            {"url": "https://news.test/2026/10/09/a-real-story", "title": "a", "content": "c"},
        ]})  # fmt: skip

    sent = []
    tavily = ws.TavilyProvider(
        "t", BLOCK, 5, httpx.MockTransport(lambda r: sent.append(r) or answer(r))
    )
    got = await tavily.search("Health news this week", "article", news=True)
    assert [r.url for r in got] == ["https://news.test/2026/10/09/a-real-story"]
    body = json.loads(sent[0].content)
    assert "exclude_domains" not in body and body["topic"] == "news" and body["max_results"] == 10
    await tavily.search("Repo rate economics explained", "article")
    assert "exclude_domains" in json.loads(sent[1].content)  # Up next unchanged


async def test_a_changed_query_makes_the_cache_stale():
    rec = Recorder()
    svc = service(rec)
    await svc.fetch("c_repo_rate", "Repo rate", "article", "policy")
    _, fresh = await svc.cached("c_repo_rate", "article", "Repo rate policy explained")
    assert fresh
    _, fresh = await svc.cached("c_repo_rate", "article", "Repo rate economics explained")
    assert not fresh


async def test_cache_is_fresh_for_48h_then_refetched():
    rec, cache = Recorder(), ws.InMemoryRecCache()
    svc = service(rec, cache=cache)
    await svc.fetch("c_repo_rate", "Repo rate", "article")
    results, fresh = await svc.cached("c_repo_rate", "article")
    assert fresh and len(results) == 1
    cache.entries[("c_repo_rate", "article")].fetched_at = datetime.now(UTC) - timedelta(hours=49)
    results, fresh = await svc.cached("c_repo_rate", "article")
    assert not fresh and len(results) == 1  # stale is still served while refetching
    await svc.refresh("c_repo_rate", "Repo rate", "article")
    assert len(rec.requests) == 2


async def test_refresh_joins_an_inflight_fetch():
    rec = Recorder()
    svc = service(rec)
    a = svc.refresh("c_repo_rate", "Repo rate", "article")
    b = svc.refresh("c_repo_rate", "Repo rate", "article")
    assert a is b
    await a
    assert len(rec.requests) == 1


async def test_daily_cap_refuses_and_degrades_to_cache(caplog):
    rec, calls, cache = Recorder(), ws.InMemorySearchCalls(), ws.InMemoryRecCache()
    svc = service(rec, settings(search_daily_cap=2), calls, cache)
    await svc.fetch("c_a", "A", "article")
    await svc.fetch("c_b", "B", "article")
    assert len(rec.requests) == 2
    assert await svc.fetch("c_c", "C", "article") == []  # nothing cached: degrade to empty
    cache.entries[("c_a", "article")].fetched_at = datetime.now(UTC) - timedelta(days=3)
    stale = await svc.fetch("c_a", "A", "article")
    assert [r.url for r in stale] == ["https://good.example/a"]  # degrade to stale cache
    assert len(rec.requests) == 2
    assert "search cap reached" in caplog.text


async def test_youtube_has_its_own_smaller_cap():
    rec, calls = Recorder(), ws.InMemorySearchCalls()
    svc = service(rec, settings(youtube_search_daily_cap=1), calls)
    await svc.fetch("c_a", "A", "video")
    await svc.fetch("c_b", "B", "video")
    assert calls.calls == {"youtube": 2}
    await svc.fetch("c_b", "B", "article")
    assert calls.calls == {"youtube": 2, "tavily": 1}


async def test_provider_errors_count_and_degrade():
    calls = ws.InMemorySearchCalls()
    failing = httpx.MockTransport(lambda r: httpx.Response(500))
    svc = ws.WebSearch(
        {"article": ws.TavilyProvider("k", BLOCK, 5, failing)},
        ws.InMemoryRecCache(),
        calls,
        settings(),
        BLOCK,
    )
    assert await svc.fetch("c_a", "A", "article") == []
    assert calls.calls == {"tavily": 1}
    assert await svc.fetch("c_a", "A", "video") == []  # no provider for this format


def test_no_providers_without_keys(monkeypatch):
    monkeypatch.setattr(ws, "FirestoreRecCache", lambda _p: ws.InMemoryRecCache())
    monkeypatch.setattr(ws, "FirestoreSearchCalls", lambda _p: ws.InMemorySearchCalls())
    svc = ws.build_service(settings())
    assert svc.formats == frozenset()


def test_keys_never_appear_in_settings_repr():
    s = settings(tavily_api_key="tvly-secret", youtube_api_key="yt-secret")
    assert "tvly-secret" not in repr(s) and "yt-secret" not in str(s.model_dump())
