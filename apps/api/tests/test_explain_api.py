"""Verified explanations end to end: two parts (restatement shared, Background per reader),
cache, report, privacy, caps (DESIGN §7).

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
from app.explain.inputs import PROMPT_VAR_KEYS, RESTATE_VAR_KEYS, ExplainInputs
from app.graph.loader import get_graph, set_graph
from app.ingest.models import StoredParagraph
from app.main import app
from app.store.content_repo import InMemoryContentStore, set_content_store
from app.store.explain_repo import ExplainRepo
from app.store.reader_repo import USER_SUBCOLLECTIONS
from tests.fakes import BG_FAIL, FAIL, GOOD_DRAFT, PASS, ExplainLLM, auth
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


def entries(docs) -> dict[str, dict]:
    return {p: d for p, d in docs.docs.items() if p.startswith("explanations/")}


def by_part(docs, part: str) -> list[dict]:
    return [d for d in entries(docs).values() if d["part"] == part]


def test_generates_both_parts_caches_them_and_serves_the_hit_without_a_model_call(
    client, fake, docs, caplog
):
    first = ask(client).json()
    assert first["kind"] == "verified" and first["cached"] is False
    assert first["author_says"] == GOOD_DRAFT["author_says"]
    assert first["background"] == GOOD_DRAFT["background"]
    assert first["thinks_in"] == "software" and first["label"] == "Yield Curve"
    assert sorted(fake.tasks()) == ["explain", "restate", "verify", "verify_background"]
    rkey, bkey = first["id"].split("-")
    r, b = docs.docs[f"explanations/{rkey}"], docs.docs[f"explanations/{bkey}"]
    assert r["part"] == "restatement" and r["verified"] is True and "band" not in r
    assert b["part"] == "background" and b["band"] == first["band"]
    assert b["thinks_in"] == "software"
    assert first["prompt_version"] == f"{r['prompt_version']}|{b['prompt_version']}"
    assert r["models"] == {"generate": "vertex_ai/quality", "verify": "vertex_ai/quality"}

    with caplog.at_level(logging.INFO, logger="app.explain.router"):
        second = ask(client).json()
    assert second["cached"] is True and second["author_says"] == first["author_says"]
    assert len(fake.calls) == 4  # no new call
    assert any(getattr(r, "cache", None) == "hit" for r in caplog.records)
    counters = docs.docs[f"ops/explain/days/{datetime.now(UTC).date().isoformat()}"]
    assert counters["hits"] == 1 and counters["generated"] == 1


def test_personas_share_one_restatement_and_get_their_own_background(client, fake, docs):
    cards = {p: ask(client, p).json() for p in ("newcomer", "trader", "policy_student")}
    assert {k: v["thinks_in"] for k, v in cards.items()} == {
        "newcomer": "software", "trader": "cricket", "policy_student": "law",
    }  # fmt: skip
    assert fake.count("restate") == 1 and fake.count("verify") == 1  # made and checked once
    assert fake.count("explain") == 3
    frames = [c["vars"]["thinks_in"] for c in fake.calls if c["task"] == "explain"]
    assert sorted(frames) == ["cricket", "law", "software"]
    assert len({v["id"].split("-")[0] for v in cards.values()}) == 1
    assert len({v["id"].split("-")[1] for v in cards.values()}) == 3
    assert len(by_part(docs, "restatement")) == 1 and len(by_part(docs, "background")) == 3


def test_prompts_get_content_and_band_only_never_identity(client, fake):
    ask(client)
    for call in fake.calls:
        blob = repr(call["vars"])
        assert "demo1" not in blob and "@" not in blob
    calls = {c["task"]: c["vars"] for c in fake.calls}
    assert set(calls["restate"]) == RESTATE_VAR_KEYS  # no band, no frame: shared by everyone
    assert "band" not in calls["restate"] and "thinks_in" not in calls["restate"]
    assert set(calls["explain"]) == PROMPT_VAR_KEYS
    assert set(calls["verify"]) == {"mode", "span", "paragraph", "author_says"}
    assert set(calls["verify_background"]) == {"mode", "span", "paragraph", "background"}


def test_a_rejected_restatement_is_regenerated_once_with_the_reasons(client, fake):
    fake.script("verify", [FAIL, PASS])
    body = ask(client).json()
    assert body["kind"] == "verified"
    restates = [c for c in fake.calls if c["task"] == "restate"]
    assert restates[0]["vars"]["feedback"] == "none"
    assert "judge_not_entailed" in restates[1]["vars"]["feedback"]
    assert fake.count("explain") == 1  # the Background passed the first time


def test_deterministic_failure_skips_the_judge_and_feeds_back(client, fake):
    bad = {"author_says": "The yield curve will invert."}  # hedge + attribution dropped
    fake.script("restate", [bad, {"author_says": GOOD_DRAFT["author_says"]}])
    assert ask(client).json()["kind"] == "verified"
    assert fake.count("restate") == 2 and fake.count("verify") == 1
    restates = [c for c in fake.calls if c["task"] == "restate"]
    assert "hedge_dropped" in restates[1]["vars"]["feedback"]


def test_restatement_rejected_twice_gives_the_definition_card(client, fake, docs):
    fake.script("verify", [FAIL])
    body = ask(client).json()
    assert body["kind"] == "definition" and body["author_says"] is None
    assert body["background"] is None
    assert body["definition"] == "Definition of c_yield_curve."
    (r,) = by_part(docs, "restatement")
    assert r["kind"] == "definition" and r["author_says"] is None  # no draft stored
    calls = len(fake.calls)
    again = ask(client, "trader").json()  # another reader: the rejection is shared
    assert again["kind"] == "definition" and len(fake.calls) == calls  # no Background made


def test_background_rejected_twice_keeps_the_verified_restatement(client, fake, docs):
    fake.script("verify_background", [BG_FAIL])
    body = ask(client).json()
    assert body["kind"] == "verified" and body["author_says"] == GOOD_DRAFT["author_says"]
    assert body["background"] is None  # the card keeps the definition in that panel
    assert body["analogy_domain"] is None
    (b,) = by_part(docs, "background")
    assert b["verified"] is False and b["background"] is None
    explains = [c for c in fake.calls if c["task"] == "explain"]
    assert (
        len(explains) == 2 and "judge_background_article_claim" in explains[1]["vars"]["feedback"]
    )


@pytest.mark.parametrize(
    "error", [llm.LLMUnavailable("down"), llm.LLMRejected("400"), llm.BudgetExceeded("cap")]
)
def test_judge_unavailable_shows_the_definition_and_caches_nothing(client, fake, docs, error):
    fake.script("verify", [error])
    fake.script("verify_background", [error])
    body = ask(client).json()
    assert body["kind"] == "definition" and body["background"] is None
    assert not entries(docs)


def test_budget_before_generation_refunds_the_daily_slot(client, fake, docs):
    fake.script("restate", [llm.BudgetExceeded("cap")])
    fake.script("explain", [llm.BudgetExceeded("cap")])
    assert ask(client).json()["kind"] == "definition"
    day = datetime.now(UTC).date().isoformat()
    assert docs.docs[f"users/demo1/explain_counts/{day}"]["count"] == 0


def test_one_request_counts_once_against_the_cap_however_many_parts(client, fake, docs):
    ask(client)  # restatement + Background: two parts, one request
    day = datetime.now(UTC).date().isoformat()
    assert docs.docs[f"users/demo1/explain_counts/{day}"]["count"] == 1


def test_daily_generation_cap_still_shows_a_shared_restatement(client, fake, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "anon_explain_daily_cap", 1)
    assert ask(client, "newcomer").json()["kind"] == "verified"
    capped = ask(client, "trader").json()  # needs a new Background: past the cap
    assert capped["kind"] == "verified" and capped["background"] is None
    assert capped["author_says"] == GOOD_DRAFT["author_says"]  # the shared part is free
    assert ask(client, "newcomer").json()["cached"] is True  # cached ones stay free


def test_report_evicts_both_parts_queues_them_and_records_the_event_once(client, fake, docs):
    first = ask(client).json()
    report = {"event_id": "r1", "content_id": "art", "concept_id": "c_yield_curve"}
    url = f"/v1/explain/{first['id']}/report?persona=newcomer"
    resp = client.post(url, json=report).json()
    assert resp == {"evicted": True, "event_applied": True}
    assert not entries(docs)
    reviews = [d for p, d in docs.docs.items() if p.startswith("explanation_reports/")]
    assert len(reviews) == 2
    assert {r["entry"]["part"] for r in reviews} == {"restatement", "background"}
    assert "uid" not in repr(reviews) and "demo1" not in repr(reviews)
    assert docs.docs["users/demo1/events/r1"]["type"] == "report_wrong"
    # replay: nothing left to evict, event not applied twice
    assert client.post(url, json=report).json() == {"evicted": False, "event_applied": False}
    # the next hover regenerates both
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
    restate = next(c for c in fake.calls if c["task"] == "restate")
    assert restate["vars"]["mode"] == "paragraph" and restate["vars"]["sentence"] == TEXT


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
    assert sorted(calls) == ["explain", "restate", "verify", "verify_background"]
    assert ra.kind == rb.kind == "verified"


def test_restate_route_and_both_judges(settings):
    assert llm.ROUTES["restate"].primary == "model_quality"
    assert llm.ROUTES["restate"].fallback == "model_fast"
    assert llm.ROUTES["verify_background"].primary == "judge_model"
    assert llm.ROUTES["verify_background"].fallback is None


def test_verify_route_uses_the_judge_model_setting(settings):
    assert llm.ROUTES["verify"].primary == "judge_model"
    assert llm._model_chain(llm.ROUTES["verify"], settings) == ["vertex_ai/quality"]
    pro = settings.model_copy(update={"model_judge": "vertex_ai/pro"})
    assert llm._model_chain(llm.ROUTES["verify"], pro) == ["vertex_ai/pro"]
