"""M9 part 1: POST /v1/content/{id}/grow grows a reader's stored page that missed growth."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import config, llm
from app.content import catalog
from app.graph import refresh
from app.graph.graph import ConceptGraph
from app.graph.grow import GrowthOutcome
from app.graph.heldout import heldout_ids
from app.graph.loader import get_graph, set_graph
from app.graph.models import ConceptGraphFile
from app.main import app
from app.store.content_repo import InMemoryContentStore, set_content_store
from app.store.docstore import get_doc_store
from app.store.reader_repo import ReaderRepo
from app.store.spend_repo import today_utc
from tests.fakes import auth
from tests.test_growth_phase2 import demands
from tests.test_growth_reopen import page
from tests.test_growth_wiring import concept

CID = "a" * 32


@pytest.fixture
def env(monkeypatch, docs):
    store = InMemoryContentStore()
    set_content_store(store)
    previous = get_graph()
    set_graph(ConceptGraph(ConceptGraphFile(version="f1", concepts=[concept("c_goal", "Goal")])))
    refresh.reset()
    catalog.reset()
    monkeypatch.setenv("GROWTH_ENABLED", "true")
    config.get_settings.cache_clear()
    yield store
    set_graph(previous)
    set_content_store(None)
    catalog.reset()
    refresh.reset()
    config.get_settings.cache_clear()


class Grower:
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    async def __call__(
        self, graph, ds, paragraphs, slots, source_cid, repo, *a, exclude=frozenset(), **k
    ):
        self.calls.append((slots, exclude))
        if self.error:
            raise self.error
        picked = [d for d in ds if d.target_id is None and d.label.lower() not in exclude][:slots]
        added = [concept(f"c_{d.label.lower()}", d.label) for d in picked]
        return GrowthOutcome(links={d.id: f"c_{d.label.lower()}" for d in picked},
                             grown={d.id for d in picked}, added=added)  # fmt: skip


async def own(uid, cid=CID):
    await ReaderRepo(get_doc_store()).add_ingested(uid, cid, datetime.now(UTC).isoformat())


def store_page(store, cid=CID, **kw):
    doc = page(**kw).model_copy(update={"content_id": cid})
    store.docs[doc.content_id] = doc
    return doc


def grow(uid="reader", anonymous=False, cid=CID):
    return TestClient(app, headers=auth(uid, anonymous=anonymous)).post(f"/v1/content/{cid}/grow")


def test_grows_a_page_that_missed_growth(env, monkeypatch, docs):
    grower = Grower()
    monkeypatch.setattr("app.graph.grow.grow", grower)
    before = store_page(env, grow_pending=True, demands=demands("Offside", "Pressing"))
    asyncio.run(own("reader"))
    resp = grow()
    assert resp.status_code == 200 and resp.json() == {
        "content_id": CID,
        "status": "grown",
        "linked": 2,
    }
    after = env.docs[CID]
    assert [d.target_id for d in after.demands] == ["c_offside", "c_pressing"]
    assert after.grow_pending is False and after.grow_tried == ["offside", "pressing"]
    assert after.paragraphs == before.paragraphs and after.grow_token is None
    assert docs.docs[f"users/reader/growth_counts/{today_utc()}"]["count"] == 2
    assert get_graph().get("c_offside") is not None
    assert grow().json()["status"] == "none"  # nothing left: no second call
    assert len(grower.calls) == 1


def test_capped_reader_keeps_the_page_pending(env, monkeypatch, docs):
    grower = Grower()
    monkeypatch.setattr("app.graph.grow.grow", grower)
    monkeypatch.setenv("GROWTH_PER_UID_DAY", "0")
    config.get_settings.cache_clear()
    store_page(env, grow_pending=True)
    asyncio.run(own("reader"))
    assert grow().json()["status"] == "capped"
    assert grower.calls == [] and env.docs[CID].grow_pending is True
    assert env.docs[CID].grow_token is None  # the claim was released


def test_only_untried_labels_are_tried_on_a_reopen(env, monkeypatch):
    grower = Grower()
    monkeypatch.setattr("app.graph.grow.grow", grower)
    store_page(env, grow_pending=True, demands=demands("Offside", "Pressing"), tried=("offside",))
    asyncio.run(own("reader"))
    assert grow().json()["linked"] == 1
    assert grower.calls == [(1, frozenset({"offside"}))]
    assert env.docs[CID].grow_tried == ["offside", "pressing"]


@pytest.mark.parametrize("case", ["flag_false", "corpus", "nothing_untried", "grown_old_page"])
def test_none_without_a_model_call(env, monkeypatch, case):
    grower = Grower()
    monkeypatch.setattr("app.graph.grow.grow", grower)
    kw = {
        "flag_false": {"grow_pending": False},
        "corpus": {"source": "fetch", "grow_pending": True},
        "nothing_untried": {"grow_pending": True, "tried": ("false nine", "offside")},
        "grown_old_page": {"calls": ("concept_define",)},
    }[case]
    store_page(env, **kw)
    asyncio.run(own("reader"))
    assert grow().json()["status"] == "none"
    assert grower.calls == [] and env.docs[CID].grow_token is None  # no claim taken


def test_a_heldout_page_never_grows(env, monkeypatch):
    grower = Grower()
    monkeypatch.setattr("app.graph.grow.grow", grower)
    held = sorted(heldout_ids())[0]
    store_page(env, cid=held, source="user_ingested", grow_pending=True)
    assert grow(cid=held).json()["status"] == "none" and grower.calls == []


def test_busy_while_another_instance_grows(env, monkeypatch):
    monkeypatch.setattr("app.graph.grow.grow", Grower())
    store_page(env, grow_pending=True)
    asyncio.run(own("reader"))
    now = datetime.now(UTC)
    asyncio.run(env.claim_growth(CID, now, now + timedelta(seconds=60)))
    resp = grow()
    assert resp.status_code == 202 and resp.json()["status"] == "growing"


def test_a_budget_refusal_is_503_and_the_page_stays_pending(env, monkeypatch):
    monkeypatch.setattr("app.graph.grow.grow", Grower(llm.BudgetExceeded("over")))
    store_page(env, grow_pending=True)
    asyncio.run(own("reader"))
    resp = grow()
    assert resp.status_code == 503 and resp.json()["error"] == "llm_budget_exceeded"
    assert env.docs[CID].grow_pending is True and env.docs[CID].grow_token is None


def test_a_finish_after_the_claim_moved_on_writes_nothing(env, monkeypatch):
    async def slow_then_stolen(graph, ds, *a, **k):
        # another instance retook the claim while this one was growing
        env.docs[CID] = env.docs[CID].model_copy(update={"grow_token": "theirs"})
        return GrowthOutcome(links={ds[0].id: "c_x"}, grown={ds[0].id}, calls=[], added=[])

    monkeypatch.setattr("app.graph.grow.grow", slow_then_stolen)
    before = store_page(env, grow_pending=True)
    asyncio.run(own("reader"))
    assert grow().json()["status"] == "none"
    assert env.docs[CID].demands == before.demands and env.docs[CID].grow_token == "theirs"


def test_another_readers_extension_page_is_404(env, monkeypatch):
    monkeypatch.setattr("app.graph.grow.grow", Grower())
    store_page(env, grow_pending=True)
    assert grow("stranger").status_code == 404
    assert grow(cid="b" * 32).status_code == 404  # not stored


def test_get_content_says_grow_pending(env):
    store_page(env, grow_pending=True)
    asyncio.run(own("reader"))
    c = TestClient(app, headers=auth("reader"))
    assert c.get(f"/v1/content/{CID}").json()["grow_pending"] is True
    env.docs[CID] = env.docs[CID].model_copy(update={"grow_pending": False})
    assert c.get(f"/v1/content/{CID}").json()["grow_pending"] is False


def test_notes_pick_up_a_concept_grown_elsewhere_a_moment_ago(env, monkeypatch):
    """G8: the reload after /grow may land on an instance that hasn't polled yet."""
    import time

    from app.store.growth_repo import get_growth_repo

    linked = [d.model_copy(update={"target_id": "c_offside"}) for d in demands("Offside")]
    store_page(env, source="user_ingested", grow_pending=False, demands=linked)
    asyncio.run(own("reader"))
    asyncio.run(get_growth_repo().create_if_absent(concept("c_offside", "Offside"), CID, {}))
    refresh.get_refresher().last_check = time.monotonic()  # polled just now: a normal read waits
    assert get_graph().get("c_offside") is None
    resp = TestClient(app, headers=auth("reader")).get(f"/v1/content/{CID}/annotations")
    assert resp.status_code == 200
    assert get_graph().get("c_offside") is None  # within SOON_S of the last poll
    refresh.get_refresher().last_check = time.monotonic() - refresh.SOON_S - 1
    TestClient(app, headers=auth("reader")).get(f"/v1/content/{CID}/annotations")
    assert get_graph().get("c_offside") is not None
