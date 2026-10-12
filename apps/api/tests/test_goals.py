"""Reading goals (M7.5 §C): CRUD, resolution privacy, progress, map filter, data rights."""

import asyncio
import logging
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app import config
from app.graph.graph import ConceptGraph
from app.graph.loader import get_graph, set_graph
from app.graph.models import Concept, ConceptGraphFile
from app.main import app
from app.me import goals as goals_api
from app.reader import goals as g
from app.reader.profile import iso_week
from app.store.docstore import get_doc_store
from app.store.reader_repo import ReaderRepo
from tests.fakes import auth, consented


def concept(cid, label, prereqs=(), b=1.5):
    return Concept(id=cid, label=label, domain="health", definition=f"{label}.", base_difficulty=b,
                   prerequisites=list(prereqs), embedding=[1.0, 0.0])  # fmt: skip


GRAPH = ConceptGraph(ConceptGraphFile(version="t", concepts=[
    concept("c_glucose", "Glucose", b=-2.0),
    concept("c_insulin", "Insulin", ["c_glucose"]),
    concept("c_insulin_resistance", "Insulin resistance", ["c_insulin"]),
]))  # fmt: skip


@pytest.fixture
def env(monkeypatch):
    previous = get_graph()
    set_graph(GRAPH)
    seen: list[list[str]] = []

    async def fake_resolve(graph, names, threshold, **kw):
        seen.append(list(names))
        hit = graph.lookup(names[0])
        return ({names[0].casefold(): hit.id} if hit else {}), ([] if hit else list(names))

    monkeypatch.setattr(goals_api, "resolve_names", fake_resolve)
    yield seen
    set_graph(previous)


def google(uid="g1"):
    c = TestClient(app, headers=auth(uid))
    consented(c)
    return c


def test_learning_goal_resolves_to_the_concept_and_its_chain_and_stores_no_text(env, caplog):
    c = google()
    with caplog.at_level(logging.INFO):
        r = c.post("/v1/me/goals", json={"type": "learning",
                                         "text": "understand insulin resistance"})  # fmt: skip
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["label"] == "Insulin resistance"
    assert [t["label"] for t in body["targets"]] == ["Glucose", "Insulin", "Insulin resistance"]
    assert body["done"] == 1 and body["total"] == 3  # glucose is easy (b = −2): known
    # The verb is stripped, so "insulin resistance" matches a label exactly: no model path
    # (decision 48 order: exact concept before resolve_names).
    assert env == []
    (doc,) = [d for _, d in asyncio.run(get_doc_store().list("users/g1/goals"))]
    assert "text" not in doc and "understand" not in str(doc)
    assert "insulin resistance" not in caplog.text.casefold()  # logs carry outcome and cost only


def test_goal_text_is_redacted_before_resolution(env):
    text = "understand insulin, mail me@x.com"
    google("g2").post("/v1/me/goals", json={"type": "learning", "text": text})
    assert "me@x.com" not in str(env) and "[REDACTED:email]" in str(env)


def test_unresolvable_goals_are_422_and_nothing_is_stored(env):
    r = google("g3").post("/v1/me/goals", json={"type": "learning", "text": "understand zzqx"})
    assert r.status_code == 422 and r.json()["error"] == "goal_not_found"
    assert asyncio.run(get_doc_store().list("users/g3/goals")) == []


def test_resolve_cap_and_goal_limit(env, monkeypatch):
    monkeypatch.setattr(config.get_settings(), "goal_resolve_daily_cap", 1)
    c = google("g4")
    assert (
        c.post("/v1/me/goals", json={"type": "learning", "text": "learn insulin"}).status_code
        == 200
    )
    capped = c.post("/v1/me/goals", json={"type": "learning", "text": "learn glucose"})
    assert capped.status_code == 429
    for n in range(4):
        assert c.post("/v1/me/goals", json={"type": "habit", "metric": "articles",
                                            "per_week": n + 1}).status_code == 200  # fmt: skip
    full = c.post("/v1/me/goals", json={"type": "habit", "metric": "minutes", "per_week": 60})
    assert full.status_code == 409


def test_habit_progress_counts_this_weeks_page_loads_and_shows_paused():
    week = {"content_ids": ["a", "b"], "words_read": 2300}
    assert g.habit_progress("articles", 5, week, False).done == 2
    assert g.habit_progress("minutes", 30, week, False).done == 10.0
    assert g.habit_progress("articles", 5, None, True).paused is True


def test_habit_goal_reads_the_current_weekly_doc(env):
    c = google("g5")

    async def week():
        async def body(t):
            t.set(f"users/g5/weekly/{iso_week(datetime.now(UTC))}",
                  {"content_ids": ["x", "y", "z"], "words_read": 460})  # fmt: skip

        await get_doc_store().run(body)

    asyncio.run(week())
    r = c.post("/v1/me/goals", json={"type": "habit", "metric": "articles", "per_week": 4}).json()
    assert (r["done"], r["total"], r["label"]) == (3, 4, "4 articles a week")


def test_goal_map_filter_feed_targets_export_and_delete(env):
    c = google("g6")
    body = {"type": "learning", "text": "understand insulin resistance"}
    goal = c.post("/v1/me/goals", json=body).json()
    sub = c.get(f"/v1/me/graph?goal={goal['id']}").json()
    assert {n["id"] for n in sub["nodes"]} == {"c_glucose", "c_insulin", "c_insulin_resistance"}
    assert len(sub["edges"]) == 2
    assert c.get("/v1/me/graph?goal=nope").status_code == 422  # not a goal id
    assert c.get("/v1/me/graph?goal=0123456789ab").status_code == 404
    assert c.delete("/v1/me/goals/a%2Fb").status_code in (404, 422)
    targets = asyncio.run(goals_api.targets_for_feed("g6"))
    assert targets["c_insulin"] == "Insulin resistance"
    repo = ReaderRepo(get_doc_store())
    assert goal["id"] in asyncio.run(repo.export("g6"))["goals"]
    assert c.delete(f"/v1/me/goals/{goal['id']}").status_code == 204
    assert c.get("/v1/me/goals").json() == []
    asyncio.run(repo.delete("g6"))
    assert asyncio.run(get_doc_store().list("users/g6/goals")) == []


def test_demo_readers_and_unconsented_readers_cannot_set_goals(env):
    demo = TestClient(app, headers=auth("d1", anonymous=True))
    assert demo.post("/v1/me/goals", json={"type": "habit", "metric": "articles",
                                           "per_week": 3}).status_code == 403  # fmt: skip
    assert demo.get("/v1/me/goals").status_code == 403
    fresh = TestClient(app, headers=auth("g7"))
    r = fresh.post("/v1/me/goals", json={"type": "habit", "metric": "articles", "per_week": 3})
    assert r.status_code == 403 and r.json()["detail"] == "consent_required"
