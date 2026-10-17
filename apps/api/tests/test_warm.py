"""Decision 69 C: the heavy lazy imports warm when a link is opened, never at startup."""

import logging
import threading

import litellm
import pytest
from fastapi.testclient import TestClient

from app import llm, warm
from app.ingest import features
from app.main import app
from tests import test_two_phase as two_phase
from tests.test_embed import FakeEmbedder
from tests.test_two_phase import CID, URL, client

# Shared with the two-phase tests.
store, fetcher, fake_llm = two_phase.store, two_phase.fetcher, two_phase.fake_llm


@pytest.fixture
def calls(monkeypatch):
    """The real run-once warm-up, its two loaders counted (overrides conftest's no-op)."""
    seen = {"litellm": 0, "nlp": 0}

    def fake_litellm():
        seen["litellm"] += 1

    def fake_nlp():
        seen["nlp"] += 1

    monkeypatch.setattr(warm, "warm", warm.real_warm)
    monkeypatch.setattr(llm, "_litellm", fake_litellm)
    monkeypatch.setattr(features, "_nlp", fake_nlp)
    warm.reset()
    yield seen
    warm.reset()


def test_the_warm_up_runs_once_however_often_it_is_asked(calls):
    threads = [threading.Thread(target=warm.warm) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    warm.warm()
    assert calls == {"litellm": 1, "nlp": 1}


def test_the_real_warm_up_imports_without_any_model_call(monkeypatch, caplog):
    monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    monkeypatch.setattr(warm, "warm", warm.real_warm)

    async def no_model_call(**_):
        raise AssertionError("the warm-up must not call a model")

    monkeypatch.setattr(litellm, "acompletion", no_model_call)
    monkeypatch.setattr(litellm, "aembedding", no_model_call)
    warm.reset()
    with caplog.at_level(logging.INFO, logger="app.warm"):
        warm.warm()
    done = [r for r in caplog.records if r.getMessage() == "warm-up done"]
    assert len(done) == 1 and done[0].warm_ms >= 0
    warm.reset()


def test_a_failed_warm_up_is_logged_and_swallowed(monkeypatch, caplog):
    def broken():
        raise ImportError("no such model")

    monkeypatch.setattr(warm, "warm", warm.real_warm)
    monkeypatch.setattr(llm, "_litellm", broken)
    warm.reset()
    with caplog.at_level(logging.WARNING, logger="app.warm"):
        warm.warm()
    failed = [r for r in caplog.records if r.getMessage() == "warm-up failed"]
    assert len(failed) == 1 and failed[0].error_class == "ImportError"
    warm.reset()


def test_startup_opening_a_link_and_analysing_all_start_it(monkeypatch, store, fetcher, fake_llm):
    """Decision 69 C2 (Sourabh, "yes", after the live check measured ≈ 7.5 s): startup starts the
    warm-up in its thread too, without waiting, so a server usually has it done before anyone
    opens a link."""
    asked: list[str] = []

    async def ready() -> None:
        asked.append("ready")

    monkeypatch.setattr(warm, "start", lambda: asked.append("start"))
    monkeypatch.setattr(warm, "ready", ready)
    with TestClient(app):  # runs the lifespan
        assert asked == ["start"]
    asked.clear()
    c = client()
    assert c.post("/v1/recs/open", json={"url": URL}).status_code == 200
    assert asked == ["start"]  # phase 1 starts it and doesn't wait
    assert c.post(f"/v1/content/{CID}/analyse").status_code == 200
    assert asked == ["start", "ready"]  # analyse waits for it, off the event loop


async def test_the_embed_log_carries_latency_and_attempts(monkeypatch, settings, spend, caplog):
    embed_settings = settings.model_copy(update={"model_embed": "vertex_ai/embed", "embed_dim": 2})
    err = litellm.RateLimitError("slow", llm_provider="vertex_ai", model="x")
    FakeEmbedder(monkeypatch, [err, "ok"])
    with caplog.at_level(logging.INFO, logger="app.llm"):
        await llm.embed(["a"], task_type="RETRIEVAL_QUERY", settings=embed_settings)
    logged = [r for r in caplog.records if r.getMessage() == "llm embed"]
    assert len(logged) == 1
    assert logged[0].attempts == 2 and logged[0].latency_ms >= 0


def test_the_ingest_log_has_its_stage_times(store, fetcher, fake_llm, caplog):
    c = client()
    c.post("/v1/recs/open", json={"url": URL})
    with caplog.at_level(logging.INFO, logger="app.ingest"):
        assert c.post(f"/v1/content/{CID}/analyse").status_code == 200
    logged = [r for r in caplog.records if r.getMessage() == "content ingested"]
    assert len(logged) == 1
    for field in ("parse_ms", "extract_ms", "link_ms", "grow_ms"):
        assert getattr(logged[0], field) >= 0, field
