"""Closing the loop (M4): interactions change the next page load's annotations.

Through the real API with in-memory stores: a demo reader taps "Knew this" and the concept is
gone on reload (and stays gone), while related concepts shift; corrections and explain_opened
move the scores too; demo persona graphs stay under Firestore's document limit.
"""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.content import router as read_router
from app.graph.graph import ConceptGraph
from app.graph.loader import get_graph, set_graph
from app.graph.models import ConceptGraphFile
from app.main import app
from app.reader.personas import PERSONAS
from app.store.content_repo import InMemoryContentStore, set_content_store
from app.store.reader_repo import FIRESTORE_DOC_LIMIT, demo_path, firestore_size, fit_demo_doc
from tests.fakes import auth, consented
from tests.test_scorer import concept, demand, doc, paras

GRAPH = ConceptGraph(
    ConceptGraphFile(
        version="loop",
        concepts=[
            concept("c_bond_yields", "finance", 0.0),
            concept("c_yield_curve", "finance", 0.0, prereqs=["c_bond_yields"]),
            concept("c_derivative_contracts", "finance", 0.1),
            concept("c_coupon", "finance", -0.5),  # in no persona's seed: moves with θ
            concept("c_treasury_bill", "finance", -0.6),
            concept("c_fiscal_consolidation", "policy", 0.1),
            concept("c_quantitative_easing", "economics", 0.2),
        ],
    )
)
IDS = [c.id for c in GRAPH.concepts if c.id != "c_bond_yields"]
NOW = datetime.now(UTC).isoformat()


@pytest.fixture
def client():
    store = InMemoryContentStore()
    demands = [demand(cid, cid, pid=f"p{i}", start=i * 100, salience=0.9)
               for i, cid in enumerate(IDS)]  # fmt: skip
    article = doc(demands, paras(len(IDS), 120)).model_copy(update={"content_id": "loop"})
    store.docs["loop"] = article
    set_content_store(store)
    read_router.reset_catalog()
    previous = get_graph()
    set_graph(GRAPH)
    yield TestClient(app, headers=auth("demo1", anonymous=True))
    set_graph(previous)
    set_content_store(None)
    read_router.reset_catalog()


def load(client, persona="newcomer"):
    body = client.get(f"/v1/content/loop/annotations?persona={persona}&debug=1").json()
    return {a["concept_id"]: a for a in body["annotations"] if a["kind"] == "span"}


def tap(client, kind, cid, eid, persona="newcomer"):
    ev = {"id": eid, "type": kind, "at": NOW, "concept_id": cid, "content_id": "loop"}
    resp = client.post("/v1/events", json={"events": [ev], "persona": persona})
    assert resp.json()["events_applied"] == 1


def test_knew_this_removes_the_concept_on_reload_and_related_concepts_shift(client, docs):
    before = load(client)
    assert {"c_derivative_contracts", "c_coupon", "c_yield_curve"} <= set(before)

    tap(client, "knew_this", "c_derivative_contracts", "k1")

    after = load(client)
    assert "c_derivative_contracts" not in after
    assert load(client) == after  # persists across reloads
    # finance θ rose (Elo), so a finance concept with no edge is now more likely known
    assert after["c_coupon"]["debug"]["p_know"] > before["c_coupon"]["debug"]["p_know"]
    assert after["c_coupon"]["score"] < before["c_coupon"]["score"]
    # other domains are untouched
    qe = "c_quantitative_easing"
    assert after[qe]["debug"]["p_know"] == before[qe]["debug"]["p_know"]
    stored = docs.docs[demo_path("demo1", "newcomer")]
    assert stored["threshold_offset"] == pytest.approx(0.02)
    assert "loop" in stored["engaged"]


def test_each_persona_learns_separately(client):
    trader_before = load(client, "trader")
    tap(client, "knew_this", "c_fiscal_consolidation", "k1", persona="newcomer")
    assert "c_fiscal_consolidation" not in load(client, "newcomer")
    assert load(client, "trader") == trader_before


def test_corrections_change_the_next_load(client):
    assert "c_yield_curve" in load(client)
    fix = client.patch("/v1/me/graph/c_yield_curve?persona=newcomer", json={"state": "known"})
    assert fix.status_code == 200
    assert "c_yield_curve" not in load(client)
    client.patch("/v1/me/graph/c_yield_curve?persona=newcomer", json={"state": "unknown"})
    assert "c_yield_curve" in load(client)


def test_explain_opened_lowers_p_know(client):
    qe = "c_quantitative_easing"  # trader: economics θ −0.3, no seeded edge
    before = load(client, "trader")[qe]["debug"]["p_know"]
    tap(client, "explain_opened", qe, "o1", persona="trader")
    after = load(client, "trader")[qe]["debug"]["p_know"]
    assert after < before


def test_signed_in_readers_start_neutral_and_learn(docs):
    store = InMemoryContentStore()
    store.docs["loop"] = doc([demand("c_coupon", "c_coupon")]).model_copy(
        update={"content_id": "loop"}
    )
    set_content_store(store)
    read_router.reset_catalog()
    previous = get_graph()
    set_graph(GRAPH)
    try:
        google = consented(TestClient(app, headers=auth("g1")))
        first = google.get("/v1/content/loop/annotations?density=guided&debug=1").json()
        spans = [a for a in first["annotations"] if a["kind"] == "span"]
        # θ = 0, b = −0.5 → prior 0.62, no edges: the neutral reader (0.38 ≥ guided 0.30)
        assert first["persona"] is None
        assert spans[0]["debug"]["p_know"] == pytest.approx(0.6225, abs=1e-4)
        assert not any(p.startswith("users/g1/knows/") for p in docs.docs)
        ev = {"id": "k1", "type": "knew_this", "at": NOW, "concept_id": "c_coupon"}
        google.post("/v1/events", json={"events": [ev]})
        assert "users/g1/knows/c_coupon" in docs.docs
        again = google.get("/v1/content/loop/annotations?density=guided").json()
        assert not [a for a in again["annotations"] if a["kind"] == "span"]
    finally:
        set_graph(previous)
        set_content_store(None)
        read_router.reset_catalog()


def test_export_and_delete_cover_demo_graphs(client, docs):
    tap(client, "knew_this", "c_coupon", "k1", persona="trader")
    body = client.get("/v1/me/export").json()
    assert "trader" in body["demo_graphs"]
    assert client.delete("/v1/me").status_code == 204
    assert not any(p.startswith("users/demo1") for p in docs.docs)


# ---------------------------------------------------------------- document size


def test_500_events_keep_a_demo_graph_under_the_limit(client, docs):
    """Many concepts and many events on one persona: the single document stays well under 1 MiB
    (≤ 5 evidence entries per edge)."""
    big = ConceptGraph(
        ConceptGraphFile(
            version="big",
            concepts=[concept(f"c_x{i:03d}", "finance", 0.0) for i in range(250)]
            + list(GRAPH.concepts),
        )
    )
    set_graph(big)
    kinds = ["knew_this", "explain_opened", "explain_helpful", "text_searched"]
    events = [
        {"id": f"e{i}", "type": kinds[i % 4], "at": NOW, "concept_id": f"c_x{i % 250:03d}",
         "content_id": "loop"}
        for i in range(500)
    ]  # fmt: skip
    for start in range(0, 500, 100):
        batch = {"events": events[start : start + 100], "persona": "trader"}
        assert client.post("/v1/events", json=batch).json()["events_applied"] == 100
    path = demo_path("demo1", "trader")
    stored = docs.docs[path]
    assert len(stored["knows"]) >= 250
    assert all(len(e["evidence"]) <= 5 for e in stored["knows"].values())
    size = len(path.encode()) + 16 + firestore_size(stored)
    assert size < 800_000 < FIRESTORE_DOC_LIMIT


def test_size_guard_drops_oldest_low_confidence_non_seed_edges():
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    t1 = datetime(2026, 6, 1, tzinfo=UTC)

    def entry(conf, at, seeded=False):
        return {"alpha": conf / 2, "beta": conf / 2, "last_seen": at, "band": "heard of",
                "evidence": [], "domain": "finance", "seeded": seeded}  # fmt: skip

    knows = {
        "c_seed": entry(1.0, t0, seeded=True),
        "c_old_weak": entry(2.0, t0),
        "c_new_weak": entry(2.0, t1),
        "c_strong": entry(9.0, t0),
        "c_touched": entry(1.0, t0),
    }
    doc_ = {"knows": knows, "theta": {}}
    full = len(b"p") + 16 + firestore_size(doc_)
    one_edge = firestore_size({"c_old_weak": knows["c_old_weak"]})
    fitted, dropped = fit_demo_doc(doc_, "p", keep={"c_touched"}, limit=full - one_edge)
    assert dropped == 1 and "c_old_weak" not in fitted["knows"]
    fitted, dropped = fit_demo_doc(doc_, "p", keep={"c_touched"}, limit=full - 2 * one_edge)
    assert set(fitted["knows"]) == {"c_seed", "c_strong", "c_touched"}
    assert fit_demo_doc(doc_, "p", keep=set(), limit=10**6) == (doc_, 0)


def test_seeded_templates_are_far_below_the_limit():
    from app.reader.personas import build_template
    from app.store.persona_repo import template_to_doc

    now = datetime.now(UTC)
    for key, spec in PERSONAS.items():
        t = template_to_doc(build_template(key, spec, GRAPH, now), GRAPH, now)
        assert firestore_size(t) < 50_000
