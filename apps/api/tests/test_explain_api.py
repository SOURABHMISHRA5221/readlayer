"""Verified explanations end to end (M5): pipeline, cache, report, privacy, caps.

Through the real API with in-memory stores and a scripted LLM (tests/fakes.ExplainLLM).
"""

import asyncio
import logging
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app import llm
from app.content import router as read_router
from app.explain import service
from app.explain.inputs import ExplainInputs
from app.graph.loader import get_graph, set_graph
from app.ingest.models import StoredParagraph
from app.main import app
from app.store.content_repo import InMemoryContentStore, set_content_store
from app.store.explain_repo import ExplainRepo
from app.store.reader_repo import USER_SUBCOLLECTIONS
from tests.fakes import FAIL, GOOD_DRAFT, PASS, ExplainLLM, auth
from tests.test_scorer import GRAPH, demand, doc

TEXT = "Analysts said the yield_curve may invert soon. Rates were 4 per cent."
NOW = datetime.now(UTC).isoformat()


@pytest.fixture
def fake(monkeypatch):
    f = ExplainLLM()
    monkeypatch.setattr(llm, "run_with_meta", f)
    return f


@pytest.fixture
def client(fake):
    store = InMemoryContentStore()
    paras = [StoredParagraph(id="p0", text=TEXT, structure=0.0)]
    store.docs["art"] = doc(
        [demand("d1", "c_yield_curve"), demand("d2", None)], paras, content_id="art"
    )
    set_content_store(store)
    read_router.reset_catalog()
    previous = get_graph()
    set_graph(GRAPH)
    yield TestClient(app, headers=auth("demo1", anonymous=True))
    set_graph(previous)
    set_content_store(None)
    read_router.reset_catalog()


def ask(client, persona="newcomer", **target):
    body = {"content_id": "art", **(target or {"demand_id": "d1"})}
    return client.post(f"/v1/explain?persona={persona}", json=body)


def test_generates_verifies_caches_and_serves_the_hit_without_a_model_call(
    client, fake, docs, caplog
):
    first = ask(client).json()
    assert first["kind"] == "verified" and first["cached"] is False
    assert first["author_says"] == GOOD_DRAFT["author_says"]
    assert first["thinks_in"] == "software" and first["label"] == "Yield Curve"
    assert fake.tasks() == ["explain", "verify"]
    entry = docs.docs[f"explanations/{first['id']}"]
    assert entry["verified"] is True and entry["prompt_version"] == first["prompt_version"]
    assert entry["models"] == {"explain": "vertex_ai/quality", "verify": "vertex_ai/quality"}

    with caplog.at_level(logging.INFO, logger="app.explain.router"):
        second = ask(client).json()
    assert second["cached"] is True and second["author_says"] == first["author_says"]
    assert fake.tasks() == ["explain", "verify"]  # no new call
    assert any(getattr(r, "cache", None) == "hit" for r in caplog.records)
    counters = docs.docs[f"ops/explain/days/{datetime.now(UTC).date().isoformat()}"]
    assert counters["hits"] == 1 and counters["generated"] == 1


def test_personas_get_their_own_frame_and_cache_entry(client, fake):
    keys = {p: ask(client, p).json() for p in ("newcomer", "trader", "policy_student")}
    assert {k: v["thinks_in"] for k, v in keys.items()} == {
        "newcomer": "software", "trader": "cricket", "policy_student": "law",
    }  # fmt: skip
    assert len({v["id"] for v in keys.values()}) == 3
    frames = [c["vars"]["thinks_in"] for c in fake.calls if c["task"] == "explain"]
    assert frames == ["software", "cricket", "law"]


def test_prompt_gets_content_and_band_only_never_identity(client, fake):
    ask(client)
    for call in fake.calls:
        blob = repr(call["vars"])
        assert "demo1" not in blob and "@" not in blob
    assert set(fake.calls[0]["vars"]) == {
        "mode", "span", "sentence", "paragraph", "concepts", "band", "band_rule", "thinks_in",
        "style", "style_rule", "feedback",
    }  # fmt: skip


def test_rejected_draft_is_regenerated_once_with_the_reasons(client, fake):
    fake.verdicts = [FAIL, PASS]
    body = ask(client).json()
    assert body["kind"] == "verified"
    explains = [c for c in fake.calls if c["task"] == "explain"]
    assert explains[0]["vars"]["feedback"] == "none"
    assert "judge_not_entailed" in explains[1]["vars"]["feedback"]


def test_deterministic_failure_skips_the_judge_and_feeds_back(client, fake):
    bad = {**GOOD_DRAFT, "author_says": "The yield curve will invert."}  # hedge + attribution
    fake.drafts = [bad, GOOD_DRAFT]
    assert ask(client).json()["kind"] == "verified"
    assert fake.tasks() == ["explain", "explain", "verify"]
    assert "hedge_dropped" in fake.calls[1]["vars"]["feedback"]


def test_two_rejections_fall_back_to_the_definition_and_cache_no_text(client, fake, docs):
    fake.verdicts = [FAIL]
    body = ask(client).json()
    assert body["kind"] == "definition" and body["author_says"] is None
    assert body["definition"] == "Definition of c_yield_curve."
    entry = docs.docs[f"explanations/{body['id']}"]
    assert entry["kind"] == "definition" and entry["author_says"] is None
    assert entry["background"] is None
    calls = len(fake.calls)
    assert ask(client).json()["cached"] is True and len(fake.calls) == calls


@pytest.mark.parametrize(
    "error", [llm.LLMUnavailable("down"), llm.LLMRejected("400"), llm.BudgetExceeded("cap")]
)
def test_judge_unavailable_shows_the_definition_and_caches_nothing(client, fake, docs, error):
    fake.verdicts = [error]
    body = ask(client).json()
    assert body["kind"] == "definition" and body["background"] is None
    assert not [p for p in docs.docs if p.startswith("explanations/")]


def test_budget_before_generation_refunds_the_daily_slot(client, fake, docs):
    fake.drafts = [llm.BudgetExceeded("cap")]
    assert ask(client).json()["kind"] == "definition"
    day = datetime.now(UTC).date().isoformat()
    assert docs.docs[f"users/demo1/explain_counts/{day}"]["count"] == 0


def test_daily_generation_cap_serves_the_definition(client, fake, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "anon_explain_daily_cap", 1)
    assert ask(client, "newcomer").json()["kind"] == "verified"
    capped = ask(client, "trader").json()  # a new key: would need a generation
    assert capped["kind"] == "definition"
    assert ask(client, "newcomer").json()["cached"] is True  # cached ones stay free


def test_report_evicts_queues_for_review_and_records_the_event_once(client, fake, docs):
    first = ask(client).json()
    report = {"event_id": "r1", "content_id": "art", "concept_id": "c_yield_curve"}
    url = f"/v1/explain/{first['id']}/report?persona=newcomer"
    resp = client.post(url, json=report).json()
    assert resp == {"evicted": True, "event_applied": True}
    assert f"explanations/{first['id']}" not in docs.docs
    reviews = [d for p, d in docs.docs.items() if p.startswith("explanation_reports/")]
    assert len(reviews) == 1 and reviews[0]["entry"]["author_says"] == GOOD_DRAFT["author_says"]
    assert "uid" not in repr(reviews[0]) and "demo1" not in repr(reviews[0])
    assert docs.docs["users/demo1/events/r1"]["type"] == "report_wrong"
    # replay: nothing left to evict, event not applied twice
    assert client.post(url, json=report).json() == {"evicted": False, "event_applied": False}
    # the next hover regenerates
    assert ask(client).json()["cached"] is False


def test_bad_requests(client):
    assert ask(client, demand_id="nope").status_code == 404
    assert ask(client, demand_id="d2").status_code == 422  # unlinked demand
    both = {"content_id": "art", "demand_id": "d1", "paragraph_id": "p0"}
    assert client.post("/v1/explain", json=both).status_code == 422
    assert (
        client.post("/v1/explain", json={"content_id": "zz", "demand_id": "d1"}).status_code == 404
    )
    assert (
        client.post(
            "/v1/explain/not-a-key/report", json={"event_id": "e", "content_id": "art"}
        ).status_code
        == 422
    )
    assert (
        TestClient(app)
        .post("/v1/explain", json={"content_id": "art", "demand_id": "d1"})
        .status_code
        == 401
    )


def test_paragraph_explainer_uses_the_same_pipeline(client, fake):
    body = ask(client, paragraph_id="p0").json()
    assert body["mode"] == "paragraph" and body["kind"] == "verified"
    assert body["label"] == "What this paragraph is saying"
    assert fake.calls[0]["vars"]["mode"] == "paragraph"
    assert fake.calls[0]["vars"]["sentence"] == TEXT


def test_explain_counts_are_covered_by_export_and_delete():
    assert "explain_counts" in USER_SUBCOLLECTIONS


async def test_concurrent_requests_for_one_key_share_one_generation(docs):
    gate = asyncio.Event()
    calls: list[str] = []

    async def slow(task, schema, prompt_vars, **_):
        calls.append(task)
        await gate.wait()
        return await ExplainLLM()(task, schema, prompt_vars)

    inputs = ExplainInputs(
        "span", "art", "p0", "yield_curve", TEXT, TEXT, (), "heard of", None, "normal"
    )

    async def yes() -> bool:
        return True

    async def nothing() -> None:
        return None

    repo = ExplainRepo(docs)
    a = asyncio.create_task(service.serve(inputs, repo, reserve=yes, refund=nothing, run=slow))
    b = asyncio.create_task(service.serve(inputs, repo, reserve=yes, refund=nothing, run=slow))
    await asyncio.sleep(0.01)
    gate.set()
    ra, rb = await asyncio.gather(a, b)
    assert calls == ["explain", "verify"]
    assert ra.kind == rb.kind == "verified"


def test_verify_route_uses_the_judge_model_setting(settings):
    assert llm.ROUTES["verify"].primary == "judge_model"
    assert llm._model_chain(llm.ROUTES["verify"], settings) == ["vertex_ai/quality"]
    pro = settings.model_copy(update={"model_judge": "vertex_ai/pro"})
    assert llm._model_chain(llm.ROUTES["verify"], pro) == ["vertex_ai/pro"]
