"""Knowledge map overview (Design pass A5) and recap bands (A4)."""

from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.graph.graph import ConceptGraph
from app.graph.loader import get_graph, set_graph
from app.graph.models import ConceptGraphFile
from app.main import app
from app.reader import overview as ov
from app.reader.model import Evidence
from tests.fakes import auth
from tests.test_scorer import NOW, concept, edge, state


def c(cid, domain="health", b=0.0, prereqs=(), freq=1):
    return concept(cid, domain, b, prereqs).model_copy(update={"doc_freq": freq})


GRAPH = ConceptGraph(ConceptGraphFile(version="ov", concepts=[
    c("c_body", b=-2.0, freq=50),                   # easy: prior-known
    c("c_cell", b=-2.0, freq=40),
    c("c_blood", prereqs=["c_body"], b=2.0, freq=30),  # hard, prerequisite known → ready
    c("c_insulin", prereqs=["c_blood"], b=2.0, freq=20),  # prerequisite not known → not ready
    c("c_glucose", prereqs=["c_cell"], b=0.0, freq=25),
    c("c_goal", prereqs=["c_cell"], b=2.0, freq=5),
    c("c_rate", domain="finance", b=-2.0, freq=60),
    c("c_bond", domain="finance", prereqs=["c_rate"], b=2.0, freq=9),
    c("c_cover", prereqs=["c_rate"], b=2.0, freq=3),  # health, its prerequisite in finance
]))  # fmt: skip


def build(st, interest=None, goals=()):
    return ov.build(GRAPH, st, interest or {}, goals, NOW)


def test_a_new_reader_without_edges_gets_an_empty_map_not_guesses():
    """Decision 69 A: no fallback to the business domains, no prior-based nodes."""
    got = build(state())
    assert got.domains == () and got.nodes == ()


def test_a_high_theta_alone_draws_nothing():
    """Before decision 69 easy concepts came out "can explain" from the prior alone."""
    got = build(state(theta={"health": 1.0}), {"health": 1.0})
    assert got.domains == () and got.nodes == ()


def test_only_concepts_with_evidence_are_solid():
    st = state(theta={"health": 2.0}, edges={"c_cell": edge(0.9)})
    by = {n.id: n for n in build(st, {"health": 1.0}).nodes}
    solid = {cid for cid, n in by.items() if not n.ready}
    assert solid == {"c_cell"}  # c_body is easier, but nothing was recorded about it


def test_a_ring_can_build_on_evidence_in_another_domain():
    known = state(edges={"c_rate": edge(0.9), "c_cell": edge(0.9)})
    by = {n.id: n for n in build(known, {"health": 1.0, "finance": 1.0}).nodes}
    assert by["c_cover"].ready  # its prerequisite (finance) has evidence
    guessed = state(theta={"finance": 2.0}, edges={"c_cell": edge(0.9)})
    by = {n.id: n for n in build(guessed, {"health": 1.0, "finance": 1.0}).nodes}
    assert "c_cover" not in by  # a guessed prerequisite doesn't make a ring


def test_a_chosen_domain_without_evidence_takes_no_slot():
    st = state(edges={"c_cell": edge(0.9)})
    got = build(st, {"finance": 1.0, "health": 0.6})  # finance chosen first, no evidence there
    assert got.domains == ("health",)


def test_the_recap_bands_still_use_the_prior():
    """/v1/me/bands reads p_know: a concept with no edge keeps its prior-based band."""
    st = state(theta={"health": 1.0})
    assert ov.p_know(GRAPH.get("c_body"), st, NOW) > 0.5


def test_ready_needs_every_prerequisite_known_and_solid_takes_precedence():
    st = state(theta={"health": -1.0}, edges={"c_body": edge(0.9), "c_cell": edge(0.9),
                                              "c_glucose": edge(0.3)})  # fmt: skip
    by = {n.id: n for n in build(st, {"health": 1.0}).nodes}
    assert by["c_blood"].ready and by["c_blood"].band == "unaware"
    assert "c_insulin" not in by  # its prerequisite isn't known
    assert by["c_glucose"].band == "heard of" and not by["c_glucose"].ready  # solid, not a ring
    assert ("c_body", "c_blood") in build(st, {"health": 1.0}).edges


def test_goal_targets_and_this_weeks_rises_are_flagged():
    risen = replace(edge(0.9), band_prev="heard of", band_changed_at=NOW - timedelta(days=1),
                    evidence=(Evidence("knew_this", 1.0, NOW),))  # fmt: skip
    st = state(edges={"c_body": risen, "c_cell": edge(0.9)})
    by = {n.id: n for n in build(st, {"health": 1.0}, goals=["c_goal"]).nodes}
    assert by["c_body"].rose_this_week and by["c_body"].recent == (("knew_this", NOW),)
    assert by["c_goal"].goal and by["c_goal"].ready


def test_caps_hold():
    st = state(edges={x.id: edge(0.9) for x in GRAPH.concepts})
    got = build(st, {"health": 1.0, "finance": 0.9})
    assert len(got.nodes) <= ov.MAX_NODES
    for d in got.domains:
        nodes = [n for n in got.nodes if n.domain == d]
        assert sum(not n.ready for n in nodes) <= ov.MAX_SOLID
        assert sum(n.ready for n in nodes) <= ov.MAX_READY


def test_routes_overview_and_bands():
    previous = get_graph()
    set_graph(GRAPH)
    try:
        client = TestClient(app, headers=auth("demo-ov", anonymous=True))
        body = client.get("/v1/me/graph?view=overview&persona=newcomer").json()
        assert body["view"] == "overview"
        assert all(n["recent"] or n["ready"] for n in body["nodes"])  # evidence only (decision 69)
        bands = client.post("/v1/me/bands?persona=newcomer",
                            json={"concept_ids": ["c_rate", "c_bond", "nope"]}).json()  # fmt: skip
        assert set(bands) == {"c_rate", "c_bond"}
        assert client.post("/v1/me/bands", json={"concept_ids": ["x"] * 51}).status_code == 422
        first = client.post(
            "/v1/me/bands?persona=newcomer", json={"concept_ids": ["c_bond"]}
        ).json()
        again = client.post(
            "/v1/me/bands?persona=newcomer", json={"concept_ids": ["c_bond"]}
        ).json()
        assert first == again  # no interaction: nothing moves
        client.patch("/v1/me/graph/c_bond?persona=newcomer", json={"state": "known"})
        after = client.post(
            "/v1/me/bands?persona=newcomer", json={"concept_ids": ["c_bond"]}
        ).json()
        order = ["unaware", "heard of", "understands", "can explain"]
        assert order.index(after["c_bond"]) > order.index(first["c_bond"])  # a correction moves it
    finally:
        set_graph(previous)


GRAPH_FILE = Path(__file__).parents[3] / "data" / "concepts.json"


@pytest.mark.skipif(not GRAPH_FILE.exists(), reason="the concept graph file is git-ignored")
def test_every_persona_keeps_an_evidence_only_map_on_the_real_graph():
    """Decision 69 A: the demo personas' maps stay full once guesses are gone (≥ 12 solid)."""
    from app.reader.personas import PERSONAS, build_template
    from app.reader.state import ReaderState

    real = ConceptGraph(ConceptGraphFile.model_validate_json(GRAPH_FILE.read_bytes()))
    for key, spec in PERSONAS.items():
        t = build_template(key, spec, real, NOW)
        domains = {c.domain for cid in t.edges if (c := real.get(cid)) is not None}
        got = ov.build(real, ReaderState(theta=t.theta, edges=t.edges), dict.fromkeys(domains, 1.0),
                       [], NOW)  # fmt: skip
        solid = [n for n in got.nodes if not n.ready]
        assert len(solid) >= 12, (key, len(solid))
        assert all(n.id in t.edges for n in solid), key
