"""M3 API: auth on every route, events, the reader's graph and profile, settings, data rights,
per-user caps, the anonymous search sub-cap, logs and CORS."""

import importlib
import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app import config, llm
from app.content import router as read_router
from app.graph.loader import get_graph, set_graph
from app.ingest import router as ingest_router
from app.main import app
from app.recs import router as recs_router
from app.recs import web_search as ws
from app.store.content_repo import InMemoryContentStore, set_content_store
from app.store.reader_repo import USER_SUBCOLLECTIONS
from tests.fakes import auth, consented, fake_fetch_and_extract, token
from tests.test_recs_api import FakeProvider
from tests.test_recs_library import DOCS, GRAPH, doc

NOW = datetime.now(UTC).isoformat()


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
    yield store, provider, calls
    ws.set_web_search(None)
    set_graph(previous)
    set_content_store(None)
    read_router.reset_catalog()


def client_for(uid="g1", anonymous=False, consent=True):
    client = TestClient(app, headers=auth(uid, anonymous))
    return consented(client) if consent and not anonymous else client


def user_docs(docs, uid):
    return {
        p: d for p, d in docs.docs.items() if p == f"users/{uid}" or p.startswith(f"users/{uid}/")
    }


def event(eid, kind="knew_this", concept="c_bond", **kw):
    return {"id": eid, "type": kind, "at": NOW, "concept_id": concept, **kw}


# ---------------------------------------------------------------- auth


def _v1_routes():
    for path, ops in app.openapi()["paths"].items():
        if path.startswith("/v1"):
            for method in sorted(ops):
                yield (
                    method.upper(),
                    path.replace("{content_id}", "main").replace("{concept_id}", "c_bond"),
                )


@pytest.mark.parametrize(("method", "path"), list(_v1_routes()))
def test_every_v1_route_needs_a_token(env, method, path):
    bare = TestClient(app)
    assert bare.request(method, path).status_code == 401
    bad = bare.request(method, path, headers={"Authorization": "Bearer forged"})
    assert bad.status_code == 401


def test_route_sweep_covers_the_m3_routes():
    paths = {p for _, p in _v1_routes()}
    expected = {
        "/v1/events", "/v1/me/graph", "/v1/me/profile", "/v1/me/export", "/v1/me",
        "/v1/me/settings", "/v1/me/graph/c_bond", "/v1/content", "/v1/recs/open",
    }  # fmt: skip
    assert expected <= paths


def test_health_is_public():
    assert TestClient(app).get("/health").status_code == 200


def test_other_sign_in_providers_are_refused(env):
    resp = TestClient(app).get("/v1/content", headers={"Authorization": "Bearer test:password:u9"})
    assert resp.status_code == 403


def test_first_request_creates_the_user_without_email(env, docs):
    client_for("g1").get("/v1/content")
    client_for("a1", anonymous=True).get("/v1/content")
    assert docs.docs["users/g1"]["is_anonymous"] is False
    assert docs.docs["users/a1"]["is_anonymous"] is True
    assert "example.com" not in json.dumps(docs.docs, default=str)


def test_logs_carry_uid_hash_never_token_or_email(env):
    import io
    import logging

    from app.log import JsonFormatter

    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        client_for("g1").get("/v1/content/main/annotations")
        client_for("g1").get("/v1/me/profile")
        TestClient(app).get("/v1/me/profile", headers={"Authorization": "Bearer forged-token"})
    finally:
        root.removeHandler(handler)
    out = buf.getvalue()
    lines = [json.loads(line) for line in out.splitlines()]
    assert lines and all(line["uid_hash"] for line in lines if line.get("status") == 200)
    assert token("g1") not in out
    assert "forged-token" not in out
    assert "g1@example.com" not in out
    assert "Bearer" not in out


def test_personas_only_for_anonymous_readers(env):
    anon = client_for("a1", anonymous=True)
    google = client_for("g1")
    assert anon.get("/v1/content/main/annotations?persona=trader").json()["persona"] == "trader"
    assert anon.get("/v1/content/main/annotations").json()["persona"] == "newcomer"
    assert google.get("/v1/content/main/annotations?persona=trader").json()["persona"] is None


# ---------------------------------------------------------------- events


def test_events_update_the_graph_and_replay_changes_nothing(env, docs):
    client = client_for("g1")
    batch = {"events": [event("e1"), event("e2", "explain_opened", "c_repo"),
                        event("e3", "paragraph_dwell", None, words=150, ms=40000)]}  # fmt: skip
    first = client.post("/v1/events", json=batch).json()
    assert first == {"applied": True, "events_applied": 3, "events_ignored": 0}
    snapshot = user_docs(docs, "g1")
    assert "users/g1/knows/c_bond" in snapshot and "users/g1/knows/c_repo" in snapshot
    assert snapshot["users/g1/domains/finance"]["theta"] > 0  # knew_this raised θ
    assert "expire_at" in snapshot["users/g1/events/e1"]  # TTL field for the 90-day policy
    again = client.post("/v1/events", json=batch).json()
    assert again == {"applied": True, "events_applied": 0, "events_ignored": 3}
    assert user_docs(docs, "g1") == snapshot


def test_unknown_concepts_are_ignored(env, docs):
    resp = client_for("g1").post("/v1/events", json={"events": [event("e1", concept="c_nope")]})
    assert resp.json()["events_ignored"] == 1
    assert "users/g1/events/e1" not in docs.docs


def test_demo_personas_copy_their_template_on_first_event(env, docs):
    client = client_for("a1", anonymous=True)
    client.get("/v1/content/main/annotations?persona=trader")
    assert "users/a1/demo_graphs/trader" not in docs.docs  # reading writes no copy
    client.post("/v1/events", json={"events": [event("e1")], "persona": "trader"})
    copy = docs.docs["users/a1/demo_graphs/trader"]
    assert copy["template_version"].startswith("trader@")
    assert "c_bond" in copy["knows"] and copy["rev"] == 1
    assert copy["theta"]["finance"] > 1.5  # seeded θ, now learned per persona
    # the reader's own graph and the other personas are untouched
    assert not any(p.startswith(("users/a1/knows/", "users/a1/domains/")) for p in docs.docs)
    assert "users/a1/demo_graphs/newcomer" not in docs.docs


def test_paused_learning_applies_nothing_but_corrections_still_apply(env, docs):
    client = client_for("g1")
    assert client.patch("/v1/me/settings", json={"learning_paused": True}).status_code == 200
    before = user_docs(docs, "g1")
    resp = client.post("/v1/events", json={"events": [event("e1")]}).json()
    assert resp["applied"] is False
    client.get("/v1/content/main/annotations")  # the trend isn't recorded either
    assert user_docs(docs, "g1") == before
    fix = client.patch("/v1/me/graph/c_bond", json={"state": "known"})
    assert fix.status_code == 200 and fix.json()["band"] in ("understands", "can explain")
    assert "users/g1/knows/c_bond" in docs.docs


def test_correction_validates_input(env):
    client = client_for("g1")
    assert client.patch("/v1/me/graph/c_nope", json={"state": "known"}).status_code == 404
    assert client.patch("/v1/me/graph/c_bond", json={"state": "maybe"}).status_code == 422


def test_event_ids_must_be_safe_document_ids(env):
    bad = {"events": [event("../users/other")]}
    assert client_for("g1").post("/v1/events", json=bad).status_code == 422


# ---------------------------------------------------------------- graph and profile


def test_graph_summary_and_domain_subgraph(env):
    client = client_for("g1")
    client.post("/v1/events", json={"events": [event("e1", "knew_this", "c_curve")]})
    summary = client.get("/v1/me/graph").json()
    assert summary["concepts_tracked"] == 1
    assert {d["domain"] for d in summary["domains"]} >= {"finance", "economics"}
    sub = client.get("/v1/me/graph?domain=finance").json()
    ids = {n["id"] for n in sub["nodes"]}
    assert ids == {"c_curve", "c_yield", "c_bond"}  # the concept plus its prerequisite closure
    assert all(e["from"] in ids and e["to"] in ids for e in sub["edges"])
    found = client.get("/v1/me/graph?domain=finance&q=yield").json()
    assert {n["id"] for n in found["nodes"]} >= {"c_yield", "c_bond"}


def test_profile_is_deterministic_and_never_calls_an_llm(env, monkeypatch):
    async def boom(*_, **__):
        raise AssertionError("no LLM call on the profile path")

    monkeypatch.setattr(llm, "run", boom)
    monkeypatch.setattr(llm, "run_with_meta", boom)
    client = client_for("g1")
    client.patch("/v1/me/settings", json={"thinks_in": ["software"]})
    client.post("/v1/events", json={"events": [event("e1"), event("e2", "knew_this", "c_curve")]})
    a = client.get("/v1/me/profile").json()
    b = client.get("/v1/me/profile").json()
    assert a == b
    assert "You think in software." in a["summary"]["text"]
    assert a["settings"] == {"density": "balanced", "explanation_style": "normal"}
    assert a["persona"] is None


def test_settings_validation(env):
    client = client_for("g1")
    ok = client.patch(
        "/v1/me/settings",
        json={"thinks_in": ["software", "cricket"], "density": "guided",
              "explanation_style": "short"},
    )  # fmt: skip
    assert ok.json() == {"thinks_in": ["cricket", "software"], "density": "guided",
                         "explanation_style": "short", "learning_paused": False}  # fmt: skip
    too_many = {"thinks_in": ["software", "cricket", "music", "law"]}
    assert client.patch("/v1/me/settings", json=too_many).status_code == 422
    assert client.patch("/v1/me/settings", json={"thinks_in": ["astrology"]}).status_code == 422
    assert client.patch("/v1/me/settings", json={"is_anonymous": True}).status_code == 422


# ---------------------------------------------------------------- data rights


def _full_flow(client, persona=None):
    q = f"?persona={persona}" if persona else ""
    client.patch("/v1/me/settings", json={"thinks_in": ["software"]})
    client.post("/v1/events", json={"events": [event("e1"), event("d1", "paragraph_dwell", None,
                                                                  words=300)]})  # fmt: skip
    client.get(f"/v1/content/main/annotations{q}")
    recs = client.get(f"/v1/content/main/recommendations{q}").json()
    client.post(
        "/v1/recs/events",
        json={"persona": persona, "events": [
            {"id": "r1", "type": "rec_shown", "item_id": recs["items"][0]["id"]}]},
    )  # fmt: skip


def test_export_returns_every_user_document(env, docs):
    client = client_for("g1")
    _full_flow(client)
    exported = client.get("/v1/me/export")
    assert exported.status_code == 200
    assert "attachment" in exported.headers["content-disposition"]
    body = exported.json()
    stored = user_docs(docs, "g1")
    assert body["user"]["thinks_in"] == ["software"]  # settings
    for path in stored:
        parts = path.split("/")
        if len(parts) == 4:
            assert parts[3] in body[parts[2]], path
    assert body["weekly"] and body["rec_signals"] and body["events"] and body["knows"]


def test_nothing_is_written_outside_the_registered_subcollections(env, docs):
    _full_flow(client_for("g1"))
    _full_flow(client_for("a1", anonymous=True), persona="trader")
    for path in docs.written:
        parts = path.split("/")
        if parts[0] == "users":
            assert len(parts) == 2 or parts[2] in USER_SUBCOLLECTIONS, path


def test_delete_removes_every_document_and_the_auth_user(env, docs, auth_admin):
    client = client_for("g1")
    _full_flow(client)
    other = client_for("g2")
    _full_flow(other)
    assert client.delete("/v1/me").status_code == 204
    assert user_docs(docs, "g1") == {}
    assert auth_admin.deleted == ["g1"]
    assert user_docs(docs, "g2")  # nobody else's data
    # A still-valid token for the deleted account can't recreate it.
    assert client.get("/v1/me/profile").status_code == 401
    assert user_docs(docs, "g1") == {}


def test_rec_signals_survive_a_restart(env):
    client = client_for("a1", anonymous=True)
    items = client.get("/v1/content/main/recommendations").json()["items"]
    gone = items[0]["id"]
    client.post("/v1/recs/events", json={"events": [{"id": "x1", "type": "rec_dismissed",
                                                     "item_id": gone}]})  # fmt: skip
    from app.recs import state

    importlib.reload(state)  # nothing in process memory carries the signal
    importlib.reload(recs_router)
    after = [i["id"] for i in client.get("/v1/content/main/recommendations").json()["items"]]
    assert gone not in after


# ---------------------------------------------------------------- caps


def _fake_ingest(store):
    async def ingest(url, source="fetch"):
        from app.ingest.urls import url_hash

        d = doc(url_hash(url), "New", "news.example", [], url=url)
        store.docs[d.content_id] = d
        return d

    return ingest


def test_signed_in_reader_gets_429_on_the_21st_new_url(env, monkeypatch):
    store, *_ = env
    monkeypatch.setattr(ingest_router, "ingest_url", _fake_ingest(store))
    client = client_for("g1")
    for i in range(20):
        assert client.post("/v1/content", json={"url": f"https://n.example/{i}"}).status_code == 200
    capped = client.post("/v1/content", json={"url": "https://n.example/20"})
    assert capped.status_code == 429 and capped.json()["error"] == "ingest_cap_reached"
    # A URL already in the library is free.
    assert client.post("/v1/content", json={"url": "https://n.example/3"}).status_code == 200
    # The cap is shared with "Open here".
    monkeypatch.setattr(recs_router, "fetch_and_extract", fake_fetch_and_extract())
    assert client.post("/v1/recs/open", json={"url": "https://n.example/x"}).status_code == 429


def test_anonymous_caps_per_reader_and_shared(env, monkeypatch):
    store, *_ = env
    monkeypatch.setattr(ingest_router, "ingest_url", _fake_ingest(store))
    monkeypatch.setenv("ANON_GLOBAL_INGEST_DAILY_CAP", "5")
    config.get_settings.cache_clear()
    a1 = client_for("a1", anonymous=True)
    for i in range(3):
        assert a1.post("/v1/content", json={"url": f"https://a.example/{i}"}).status_code == 200
    assert a1.post("/v1/content", json={"url": "https://a.example/3"}).status_code == 429
    a2 = client_for("a2", anonymous=True)
    assert a2.post("/v1/content", json={"url": "https://b.example/0"}).status_code == 200
    assert a2.post("/v1/content", json={"url": "https://b.example/1"}).status_code == 200
    # 5 anonymous ingests today across everyone: a fresh anonymous account gets none.
    a3 = client_for("a3", anonymous=True)
    assert a3.post("/v1/content", json={"url": "https://c.example/0"}).status_code == 429
    # Signed-in readers are not affected by the anonymous pool.
    google = client_for("g1")
    assert google.post("/v1/content", json={"url": "https://d.example/0"}).status_code == 200


def test_failed_ingest_refunds_the_slot(env, monkeypatch, docs):
    from app.ingest.safe_fetch import FetchError

    async def failing(url, source="fetch"):
        raise FetchError("timeout", "too slow")

    monkeypatch.setattr(ingest_router, "ingest_url", failing)
    resp = client_for("g1").post("/v1/content", json={"url": "https://slow.example/a"})
    assert resp.status_code == 504
    counts = [d for p, d in docs.docs.items() if p.startswith("users/g1/ingest_counts/")]
    assert counts and counts[0]["count"] == 0


def test_anonymous_searches_share_a_daily_sub_cap(env, monkeypatch):
    _, provider, calls = env
    monkeypatch.setenv("ANON_SEARCH_DAILY_CAP", "0")
    config.get_settings.cache_clear()
    ws.get_web_search()._settings = config.get_settings()
    anon = client_for("a1", anonymous=True)
    body = anon.get("/v1/content/main/recommendations").json()
    assert provider.queries == []  # nothing searched for the anonymous reader
    assert body["pending"] is False
    assert {i["kind"] for i in body["items"]} == {"library"}
    # Signed-in readers still search, and the anonymous counter doesn't move.
    client_for("g1").get("/v1/content/main/recommendations")
    import time

    for _ in range(50):
        if provider.queries:
            break
        time.sleep(0.01)
    assert provider.queries
    assert calls.anonymous == 0


async def test_anonymous_sub_cap_is_enforced_at_reservation(env, monkeypatch):
    _, provider, calls = env
    monkeypatch.setenv("ANON_SEARCH_DAILY_CAP", "2")
    config.get_settings.cache_clear()
    web = ws.get_web_search()
    web._settings = config.get_settings()
    await web.fetch("c_bond", "Bond", "article", "finance", anonymous=True)
    await web.fetch("c_bond", "Bond", "podcast", "finance", anonymous=True)
    await web.fetch("c_yield", "Bond yield", "article", "finance", anonymous=True)
    assert len(provider.queries) == 2
    assert calls.anonymous == 2
    assert await web.anonymous_allowance_left() is False
    # Cached results are still served to anonymous readers past the cap.
    results, _ = await web.cached("c_bond", "article")
    assert results


def test_annotation_reads_are_rate_limited_tighter_for_anonymous(env, monkeypatch):
    monkeypatch.setenv("RATE_ANNOTATIONS_ANON_PER_MIN", "2")
    monkeypatch.setenv("RATE_ANNOTATIONS_PER_MIN", "3")
    config.get_settings.cache_clear()
    anon = client_for("a1", anonymous=True)
    codes = [anon.get("/v1/content/main/annotations").status_code for _ in range(3)]
    assert codes == [200, 200, 429]
    google = client_for("g1")
    codes = [google.get("/v1/content/main/annotations").status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]
    assert "Retry-After" in google.get("/v1/content/main/annotations").headers


# ---------------------------------------------------------------- CORS


def test_cors_allows_only_the_configured_origins(monkeypatch):
    import app.main

    monkeypatch.setenv("CORS_ORIGINS", "https://readlayer.web.app")
    config.get_settings.cache_clear()
    try:
        client = TestClient(importlib.reload(app.main).app)
        pre = {"Access-Control-Request-Method": "GET",
               "Access-Control-Request-Headers": "authorization"}  # fmt: skip
        ok = client.options("/v1/content", headers={"Origin": "https://readlayer.web.app", **pre})
        assert ok.status_code == 200
        assert ok.headers["access-control-allow-origin"] == "https://readlayer.web.app"
        evil = client.options("/v1/content", headers={"Origin": "https://evil.example", **pre})
        assert evil.status_code == 400
        assert "access-control-allow-origin" not in evil.headers
        simple = client.get("/health", headers={"Origin": "https://evil.example"})
        assert "access-control-allow-origin" not in simple.headers
    finally:
        monkeypatch.delenv("CORS_ORIGINS")
        config.get_settings.cache_clear()
        importlib.reload(app.main)
