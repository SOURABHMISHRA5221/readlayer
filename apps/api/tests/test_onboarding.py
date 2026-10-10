"""Consent, onboarding and calibration (M7, DESIGN §4, §8, §11.4)."""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.content import router as read_router
from app.graph.graph import ConceptGraph
from app.graph.loader import get_graph, set_graph
from app.graph.models import DOMAINS, Concept, ConceptGraphFile
from app.ingest.models import StoredParagraph
from app.main import app
from app.reader import model, onboarding
from app.store.content_repo import InMemoryContentStore, set_content_store
from tests.fakes import auth, consented
from tests.test_scorer import demand, doc

NOW = datetime(2026, 10, 10, tzinfo=UTC)


def concept(cid: str, domain: str, b: float, freq: int) -> Concept:
    return Concept(
        id=cid,
        label=cid.removeprefix("c_").replace("_", " ").title(),
        domain=domain,
        definition=f"Definition of {cid}.",
        base_difficulty=b,
        doc_freq=freq,
        embedding=[1.0, 0.0],
    )


CONCEPTS = [
    concept(f"c_{d}_{i}", d, round(-2 + i * 0.4, 2), 100 - i)
    for d in ("finance", "economics", "business", "policy")
    for i in range(10)
]
GRAPH = ConceptGraph(ConceptGraphFile(version="t", concepts=CONCEPTS))


@pytest.fixture(autouse=True)
def small_domains_qualify(monkeypatch):
    """GRAPH has 10 concepts per domain; the real bar (30) is tested on its own below."""
    monkeypatch.setattr(onboarding, "CALIBRATION_MIN_CONCEPTS", 10)


@pytest.fixture
def env():
    store = InMemoryContentStore()
    liked = doc(
        [
            demand("d1", "c_finance_3", salience=0.9),
            demand("d2", "c_finance_4", salience=0.5),  # not salient enough
            demand("d3", None, salience=0.9),  # unlinked
        ],
        [StoredParagraph(id="p0", text="x", structure=0.0)],
        content_id="liked",
    )
    store.docs["liked"] = liked
    set_content_store(store)
    read_router.reset_catalog()
    previous = get_graph()
    set_graph(GRAPH)
    yield store
    set_graph(previous)
    set_content_store(None)
    read_router.reset_catalog()


def google(uid: str = "g1") -> TestClient:
    return TestClient(app, headers=auth(uid))


ANSWERS = {
    "field": "software",
    "interests": ["finance", "economics"],
    "comfort": {"finance": "new", "economics": "comfortable"},
    "thinks_in": ["software"],
    "liked_content_ids": ["liked"],
}


# ---------------------------------------------------------------- pure logic


def test_starting_theta_and_interests_follow_the_answers():
    assert onboarding.starting_theta({"finance": "new", "policy": "expert"}) == {
        "finance": -1.5, "policy": 1.5,
    }  # fmt: skip
    got = onboarding.interests(["finance"])
    assert got["finance"] == 1.0 and got["policy"] == 0.3 and len(got) == len(DOMAINS) == 14


def test_calibration_picks_round_robin_closest_to_theta_and_never_repeats():
    theta = {"finance": -1.5, "economics": 0.5}
    asked: list[str] = []
    seen_domains = []
    for _ in range(onboarding.CALIBRATION_ITEMS):
        item = onboarding.next_item(GRAPH, ["economics", "finance"], theta, asked)
        assert item is not None and item.id not in asked
        seen_domains.append(item.domain)
        asked.append(item.id)
    # DOMAINS order (economics, finance, ...) alternates; the first pick is closest to θ there.
    assert seen_domains[:4] == ["economics", "finance", "economics", "finance"]
    assert asked[0] == "c_economics_6"  # b = 0.4, closest to θ 0.5
    assert asked[1] == "c_finance_1"  # b = −1.6, closest to θ −1.5
    assert onboarding.next_item(GRAPH, ["finance"], theta, asked) is None  # 8 asked: done
    again = onboarding.next_item(GRAPH, ["economics", "finance"], theta, [])
    assert again is not None and again.id == "c_economics_6"  # deterministic


def test_calibration_offers_only_interests_with_enough_concepts(monkeypatch):
    monkeypatch.setattr(onboarding, "CALIBRATION_MIN_CONCEPTS", 30)
    health = [concept(f"c_health_{i}", "health", round(-2 + i * 0.1, 2), 0) for i in range(30)]
    sports = [concept(f"c_sports_{i}", "sports", 0.0, 0) for i in range(29)]  # one short
    graph = ConceptGraph(ConceptGraphFile(version="t", concepts=CONCEPTS + health + sports))
    assert onboarding.calibration_domains(graph, ["sports", "health"]) == ["health"]
    item = onboarding.next_item(graph, ["sports", "health"], {}, [])
    assert item is not None and item.domain == "health"
    # nothing qualifies → the four business domains (here they have 10 each, so none is "ready",
    # but they are the fallback list; their pools still offer concepts)
    assert onboarding.calibration_domains(graph, ["sports"]) == [
        "economics", "finance", "business", "policy",
    ]  # fmt: skip


def test_seeded_domain_pool_offers_its_most_basic_concepts_first():
    seeds = [concept(f"c_sci_{i}", "science", b, 0) for i, b in enumerate([1.5, -1.0, 0.2])]
    graph = ConceptGraph(ConceptGraphFile(version="t", concepts=seeds))
    assert [c.id for c in onboarding.calibration_pool(graph, "science")] == [
        "c_sci_1", "c_sci_2", "c_sci_0",
    ]  # fmt: skip


def test_answers_move_the_concept_and_theta_with_onboarding_strength():
    c = GRAPH.get("c_finance_5")
    assert c is not None
    known = onboarding.apply_answer(c, None, 0.0, "explain", NOW)
    heard = onboarding.apply_answer(c, None, 0.0, "heard", NOW)
    new = onboarding.apply_answer(c, None, 0.0, "none", NOW)
    assert model.p_know(known.edge) > model.p_know(heard.edge) > model.p_know(new.edge)
    assert known.edge.evidence[-1].w == 3.0 and heard.edge.evidence[-1].w == -1.5
    assert new.edge.evidence[-1].w == -3.0
    expected = 0.0 + 0.3 * (1.0 - model.sigmoid(0.0 - c.base_difficulty))
    assert known.theta == pytest.approx(expected)
    assert new.theta < 0.0 < known.theta


# ---------------------------------------------------------------- API


def test_onboarding_is_for_signed_in_readers_who_consented(env):
    anon = TestClient(app, headers=auth("a1", anonymous=True))
    assert anon.post("/v1/onboarding", json=ANSWERS).status_code == 403
    assert anon.post("/v1/me/consent", json={"version": "consent-v1"}).status_code == 403
    g = google()
    assert g.post("/v1/onboarding", json=ANSWERS).status_code == 409  # consent first
    assert g.post("/v1/me/consent", json={"version": "v0"}).status_code == 422
    assert g.get("/v1/me/profile").json()["onboarding"] == {
        "consented": False, "done": False, "step": "consent",
    }  # fmt: skip


def test_onboarding_sets_theta_interest_frames_and_liked_nudges(env, docs):
    g = consented(google())
    assert g.get("/v1/me/profile").json()["onboarding"]["step"] == "onboarding"
    resp = g.post("/v1/onboarding", json=ANSWERS)
    assert resp.status_code == 200 and resp.json()["liked_concepts"] == 1
    fin = docs.docs["users/g1/domains/finance"]
    assert fin["theta"] == -1.5 and fin["interest"] == 1.0
    assert docs.docs["users/g1/domains/policy"]["interest"] == 0.3
    nudged = docs.docs["users/g1/knows/c_finance_3"]
    assert nudged["evidence"][-1]["type"] == "liked_article_mention"
    assert "users/g1/knows/c_finance_4" not in docs.docs  # below the salience bar
    user = docs.docs["users/g1"]
    assert user["thinks_in"] == ["software"] and user["field"] == "software"
    assert user["onboarding"]["interests"] == ["finance", "economics"]
    profile = g.get("/v1/me/profile").json()
    assert profile["onboarding"]["step"] == "calibration" and profile["thinks_in"] == ["software"]


def test_calibration_eight_answers_then_done(env, docs):
    g = consented(google())
    g.post("/v1/onboarding", json=ANSWERS)
    for i in range(onboarding.CALIBRATION_ITEMS):
        nxt = g.get("/v1/calibration/next").json()
        assert nxt["done"] is False and nxt["asked"] == i
        cid = nxt["item"]["concept_id"]
        # Answering anything but the current item is refused.
        wrong = "c_policy_9" if cid != "c_policy_9" else "c_policy_8"
        assert (
            g.post(
                "/v1/calibration/answer", json={"concept_id": wrong, "answer": "explain"}
            ).status_code
            == 409
        )  # noqa: E501
        body = g.post("/v1/calibration/answer", json={"concept_id": cid, "answer": "heard"}).json()
        assert body["asked"] == i + 1
        assert docs.docs[f"users/g1/knows/{cid}"]["evidence"][-1]["type"] == "calibration_answer"
    assert body["done"] is True
    assert g.get("/v1/calibration/next").json()["done"] is True
    assert g.get("/v1/me/profile").json()["onboarding"] == {
        "consented": True, "done": True, "step": "done",
    }  # fmt: skip


def test_skip_finishes_onboarding_with_what_was_answered(env):
    g = consented(google())
    g.post("/v1/onboarding", json=ANSWERS)
    first = g.get("/v1/calibration/next").json()["item"]["concept_id"]
    g.post("/v1/calibration/answer", json={"concept_id": first, "answer": "explain"})
    assert g.post("/v1/calibration/skip").json() == {"done": True}
    assert g.get("/v1/me/profile").json()["onboarding"]["done"] is True


def test_nothing_is_recorded_for_a_signed_in_reader_before_consent(env, docs):
    g = google("g2")
    events = {
        "events": [
            {"id": "e1", "type": "knew_this", "at": NOW.isoformat(), "concept_id": "c_finance_1",
             "content_id": "liked"},
        ]
    }  # fmt: skip
    resp = g.post("/v1/events", json=events).json()
    assert resp["applied"] is False and resp["events_applied"] == 0
    assert g.get("/v1/content/liked/annotations").status_code == 200
    assert g.patch("/v1/me/graph/c_finance_1", json={"state": "known"}).status_code == 403
    assert g.patch("/v1/me/settings", json={"density": "guided"}).status_code == 403
    recs = g.post("/v1/recs/events", json={"events": [
        {"id": "r1", "type": "rec_clicked", "item_id": "lib:x"}]}).json()  # fmt: skip
    assert recs == {"applied": 0, "ignored": 1}
    written = sorted(p for p in docs.docs if p.startswith("users/g2"))
    assert written == ["users/g2"]  # only the bare profile doc from sign-in
    # Leaving is always possible.
    assert g.get("/v1/me/export").status_code == 200
    assert g.delete("/v1/me").status_code == 204


def test_demo_profile_shows_the_personas_frame(env):
    anon = TestClient(app, headers=auth("a2", anonymous=True))
    trader = anon.get("/v1/me/profile?persona=trader").json()
    assert trader["thinks_in"] == ["cricket"] and "cricket" in trader["summary"]["text"]
    assert trader["onboarding"]["done"] is True


def test_map_nodes_carry_their_last_evidence_items(env):
    g = consented(google())
    g.post("/v1/onboarding", json=ANSWERS)
    cid = g.get("/v1/calibration/next").json()["item"]["concept_id"]
    g.post("/v1/calibration/answer", json={"concept_id": cid, "answer": "explain"})
    g.patch(f"/v1/me/graph/{cid}", json={"state": "unknown"})
    domain = cid.split("_")[1]
    nodes = {n["id"]: n for n in g.get(f"/v1/me/graph?domain={domain}").json()["nodes"]}
    recent = nodes[cid]["recent"]
    assert [r["type"] for r in recent] == ["correction", "calibration_answer"]  # newest first
    assert len(recent) <= 3


def test_the_summary_names_only_domains_the_reader_rated_or_reads_in(env):
    g = consented(google())
    g.post(
        "/v1/onboarding", json={**ANSWERS, "comfort": {"finance": "new"}, "liked_content_ids": []}
    )
    profile = g.get("/v1/me/profile").json()
    assert profile["summary"]["text"].startswith("New to finance.")
    rated = {d["domain"]: d["rated"] for d in profile["domains"]}
    assert rated == {d: d == "finance" for d in DOMAINS}
