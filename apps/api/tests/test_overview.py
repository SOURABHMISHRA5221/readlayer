"""Knowledge map overview (Design pass A5) and recap bands (A4)."""

from dataclasses import replace
from datetime import timedelta

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
]))  # fmt: skip


def build(st, interest=None, goals=()):
    return ov.build(GRAPH, st, interest or {}, goals, NOW)


def test_a_new_reader_without_edges_or_interest_still_gets_a_map():
    got = build(state())
    assert got.domains[:2] == ("economics", "finance")  # the business domains
    assert {n.id for n in got.nodes} >= {"c_rate"}  # prior-based solid node, never empty


def test_a_no_edges_reader_with_a_high_theta_gets_solid_nodes_and_ready_rings():
    got = build(state(theta={"health": 1.0}), {"health": 1.0})
    by = {n.id: n for n in got.nodes}
    assert got.domains == ("health",)
    assert not by["c_body"].ready and by["c_body"].band in ("understands", "can explain")
    assert by["c_body"].recent == ()  # prior-only: no evidence


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
    got = build(state(theta={d: 2.0 for d in ("health", "finance")}),
                {"health": 1.0, "finance": 0.9})  # fmt: skip
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
        assert body["view"] == "overview" and body["nodes"]
        bands = client.post("/v1/me/bands?persona=newcomer",
                            json={"concept_ids": ["c_rate", "c_bond", "nope"]}).json()  # fmt: skip
        assert set(bands) == {"c_rate", "c_bond"}
        assert client.post("/v1/me/bands", json={"concept_ids": ["x"] * 51}).status_code == 422
    finally:
        set_graph(previous)
