"""Decision 68 K: knowledge comes from screen 1 (what you do, where you read from), never from
screen 2's taps."""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.content import router as read_router
from app.graph.graph import ConceptGraph
from app.graph.loader import get_graph, set_graph
from app.graph.models import Concept, ConceptGraphFile
from app.main import app
from app.reader import model, onboarding
from app.reader.profile import moved_up_this_week
from app.store.content_repo import InMemoryContentStore, set_content_store
from app.store.reader_repo import edge_from_doc
from tests.fakes import auth, consented

NOW = datetime(2026, 10, 17, tzinfo=UTC)


def c(cid: str, domain: str, b: float, freq: int, jur: str = "global") -> Concept:
    return Concept(id=cid, label=cid, domain=domain, definition=f"{cid}.", base_difficulty=b,
                   doc_freq=freq, jurisdiction=jur, embedding=[1.0, 0.0])  # fmt: skip


GRAPH = ConceptGraph(ConceptGraphFile(version="k", concepts=[
    c("c_rbi", "finance", 0.5, 40, "IN"),
    c("c_gst", "policy", 0.6, 30, "IN"),
    c("c_sebi", "finance", 0.4, 20, "IN"),
    c("c_lakh", "economics", -2.0, 50, "IN"),  # prior already high: would land ≥ 0.8, skipped
    c("c_rare_in", "culture", 0.0, 2, "IN"),  # doc_freq < 3: noise, skipped
    c("c_fed", "finance", 0.5, 45, "US"),
    c("c_api", "technology", 0.0, 60),
]))  # fmt: skip


# ---------------------------------------------------------------- pure


def test_field_theta_maps_a_field_to_its_domains_at_comfortable():
    lvl = onboarding.LEVEL_THETA["comfortable"]
    assert onboarding.FIELD_THETA["software"] == ("technology",)
    assert set(onboarding.FIELD_THETA["finance"]) == {"finance", "economics"}
    assert onboarding.FIELD_THETA["design"] == () and onboarding.FIELD_THETA["other"] == ()
    assert onboarding.first_theta("software", None, {}) == {"technology": lvl}


def test_first_theta_resets_a_previous_field_and_comfort_wins():
    lvl = onboarding.LEVEL_THETA["comfortable"]
    assert onboarding.first_theta("law", "software", {}) == {"technology": 0.0, "law": lvl}
    assert onboarding.first_theta("law", "law", {}) == {"law": lvl}
    got = onboarding.first_theta("law", "software", {"law": "new", "technology": "some"})
    assert got == {"technology": -0.5, "law": -1.5}


def test_home_terms_are_the_countrys_frequent_concepts():
    assert [x.id for x in onboarding.home_terms(GRAPH, "IN")] == [
        "c_lakh",
        "c_rbi",
        "c_gst",
        "c_sebi",
    ]
    assert [x.id for x in onboarding.home_terms(GRAPH, "US")] == ["c_fed"]
    assert onboarding.home_terms(GRAPH, "other") == [] and onboarding.home_terms(GRAPH, None) == []


def test_home_nudge_is_gentle_once_and_never_a_band_move():
    rbi = GRAPH.get("c_rbi")
    edge = onboarding.apply_home(rbi, None, 0.0, NOW)
    assert edge is not None
    assert [e.type for e in edge.evidence] == ["home_country"]
    assert edge.evidence[0].w == model.EVIDENCE_WEIGHTS["home_country"] == 0.2
    assert edge.band_prev is None and edge.band_changed_at is None
    assert onboarding.apply_home(rbi, edge, 0.0, NOW) is None  # already nudged
    assert moved_up_this_week({"c_rbi": edge}, NOW) == []


def test_home_nudge_skips_what_would_land_at_or_above_point_eight():
    assert onboarding.apply_home(GRAPH.get("c_lakh"), None, 0.0, NOW) is None  # from the prior
    strong = model.init_edge(0.5, NOW)
    for _ in range(2):  # two "Knew this": p ≈ 0.83 already
        strong = model.apply_evidence(
            strong, 0.5, "knew_this", model.EVIDENCE_WEIGHTS["knew_this"], NOW
        )
    assert onboarding.apply_home(GRAPH.get("c_rbi"), strong, 0.0, NOW) is None  # from the edge


# ---------------------------------------------------------------- through the API


@pytest.fixture
def env():
    set_content_store(InMemoryContentStore())
    read_router.reset_catalog()
    previous = get_graph()
    set_graph(GRAPH)
    yield
    set_graph(previous)
    set_content_store(None)
    read_router.reset_catalog()


def answers(field="software", country="IN", **extra):
    return {"field": field, "interests": ["finance"], "thinks_in": [], "country": country, **extra}


def home_entries(docs, uid="g1") -> dict[str, int]:
    out = {}
    for path, d in docs.docs.items():
        if path.startswith(f"users/{uid}/knows/"):
            out[path.rsplit("/", 1)[1]] = sum(e["type"] == "home_country" for e in d["evidence"])
    return out


def test_screen_one_sets_field_theta_and_home_terms_once(env, docs):
    g = consented(TestClient(app, headers=auth("g1")))
    assert g.post("/v1/onboarding", json=answers()).status_code == 200
    lvl = onboarding.LEVEL_THETA["comfortable"]
    assert docs.docs["users/g1/domains/technology"]["theta"] == lvl
    assert home_entries(docs) == {"c_rbi": 1, "c_gst": 1, "c_sebi": 1}  # c_lakh ≥ 0.8, skipped
    g.post("/v1/onboarding", json=answers())  # Edit → Continue
    assert home_entries(docs) == {"c_rbi": 1, "c_gst": 1, "c_sebi": 1}
    g.post("/v1/onboarding", json=answers(field="law"))  # field changed before finishing
    assert docs.docs["users/g1/domains/technology"]["theta"] == 0.0
    assert docs.docs["users/g1/domains/law"]["theta"] == lvl
    edges = {k.rsplit("/", 1)[1]: edge_from_doc(v) for k, v in docs.docs.items()
             if k.startswith("users/g1/knows/")}  # fmt: skip
    assert moved_up_this_week(edges, datetime.now(UTC)) == []


def test_a_redo_keeps_theta_and_adds_no_second_home_entry(env, docs):
    g = consented(TestClient(app, headers=auth("g1")))
    g.post("/v1/onboarding", json=answers())
    assert g.post("/v1/onboarding/finish").status_code == 200
    assert g.post("/v1/onboarding/redo").status_code == 200
    docs.docs["users/g1/domains/technology"]["theta"] = 1.2  # moved by reading since
    assert g.post("/v1/onboarding", json=answers(field="finance")).status_code == 200
    assert docs.docs["users/g1/domains/technology"]["theta"] == 1.2  # not on a redo
    assert "users/g1/domains/economics" not in docs.docs or (
        docs.docs["users/g1/domains/economics"].get("theta", 0.0) == 0.0
    )
    assert home_entries(docs) == {"c_rbi": 1, "c_gst": 1, "c_sebi": 1}


def test_no_country_or_other_writes_no_home_terms(env, docs):
    g = consented(TestClient(app, headers=auth("g1")))
    g.post("/v1/onboarding", json=answers(country="other"))
    assert home_entries(docs) == {}


def test_formats_are_stored_returned_deduplicated_and_kept(env, docs):
    """Decision 68 F1: optional at the API; empty keeps the stored answer; a redo keeps it."""
    g = consented(TestClient(app, headers=auth("g1")))
    g.post("/v1/onboarding", json=answers(formats=["video", "video", "podcast"]))
    assert docs.docs["users/g1"]["formats"] == ["video", "podcast"]
    assert g.get("/v1/me/profile").json()["onboarding"]["formats"] == ["video", "podcast"]
    g.post("/v1/onboarding", json=answers())  # an old client sends none: kept
    assert docs.docs["users/g1"]["formats"] == ["video", "podcast"]
    g.post("/v1/onboarding/finish")
    g.post("/v1/onboarding/redo")
    g.post("/v1/onboarding", json=answers())
    assert docs.docs["users/g1"]["formats"] == ["video", "podcast"]
    g.post("/v1/onboarding", json=answers(formats=["article"]))
    assert docs.docs["users/g1"]["formats"] == ["article"]
    assert g.post("/v1/onboarding", json=answers(formats=["audio"])).status_code == 422


def test_served_order_survives_a_shuffled_map():
    """Firestore doesn't keep a map's key order: cards keep theirs by the stored position."""
    from app.me.onboarding_flow import served_order

    offered = {"z": {"n": 0}, "a": {"n": 2}, "m": {"n": 1}, "old": {}}
    assert served_order(offered) == ["z", "m", "a", "old"]
    stored = onboarding.offer({}, [("x", "economics", ()), ("b", "economics", ())], [])
    assert served_order(dict(reversed(list(stored.items())))) == ["x", "b"]


def test_a_finished_reader_outside_a_redo_keeps_earned_theta(env, docs):
    g = consented(TestClient(app, headers=auth("g1")))
    g.post("/v1/onboarding", json=answers())
    g.post("/v1/onboarding/finish")
    docs.docs["users/g1/domains/technology"]["theta"] = 1.3
    g.post("/v1/onboarding", json=answers())  # a stale tab
    assert docs.docs["users/g1/domains/technology"]["theta"] == 1.3


def test_home_terms_alone_give_a_topic_no_level(env, docs):
    """Decision 69 A2: a few recorded country terms in a topic don't make its untouched level
    (θ 0) "comfortable"; the topic shows its ideas but no level word."""
    g = consented(TestClient(app, headers=auth("g1")))
    g.post("/v1/onboarding", json=answers())
    profile = g.get("/v1/me/profile").json()
    graph = get_graph()
    home = {graph.get(cid).domain for cid in home_entries(docs)} - {"technology"}
    assert home  # the fixture's home terms sit outside the field's domain
    rated = {d["domain"]: d["rated"] for d in profile["domains"]}
    assert rated["technology"] is True  # the field set its level
    assert not any(rated[d] for d in home)
    text = profile["summary"]["text"]
    assert all(d not in text for d in home), text


def test_a_quick_check_answer_rates_its_topic(env, docs):
    """Exactly-zero θ after an answer is pinned by test_reader_logic's per-kind test."""
    g = consented(TestClient(app, headers=auth("g1")))
    g.post("/v1/onboarding", json=answers())
    item = g.get("/v1/calibration/set").json()["items"][0]
    answer = {"concept_id": item["concept_id"], "answer": "heard"}
    assert g.post("/v1/calibration/answer", json=answer).status_code == 200
    rated = {d["domain"]: d["rated"] for d in g.get("/v1/me/profile").json()["domains"]}
    assert rated[item["domain"]] is True


def test_demo_personas_are_rated_exactly_where_their_level_is_set(env):
    from app.reader.personas import PERSONAS

    anon = TestClient(app, headers=auth("demo-a2", anonymous=True))
    for key, spec in PERSONAS.items():
        body = anon.get(f"/v1/me/profile?persona={key}").json()
        rated = {d["domain"] for d in body["domains"] if d["rated"]}
        assert rated == {d for d, t in spec.theta.items() if abs(t) > 1e-9}, key
