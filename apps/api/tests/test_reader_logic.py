"""Pure reader logic: event application, profile template, knowledge-map subgraph."""

from datetime import UTC, datetime, timedelta

import networkx as nx
import pytest

from app.graph.graph import ConceptGraph
from app.graph.models import Concept, ConceptGraphFile
from app.reader import model, profile
from app.reader.events import ConceptRef, ReaderEvent, apply_events, correction
from app.reader.model import Edge
from app.reader.subgraph import MAX_NODES, knowledge_subgraph

NOW = datetime(2026, 10, 7, 12, tzinfo=UTC)
REFS = {"c_repo": ConceptRef("economics", 0.5), "c_bond": ConceptRef("finance", -0.5)}


def ev(eid, kind, cid="c_repo", **kw):
    return ReaderEvent(id=eid, type=kind, at=NOW, concept_id=cid, **kw)


# ---------------------------------------------------------------- events


def test_knew_this_creates_an_edge_from_the_prior_and_raises_theta():
    out = apply_events([ev("e1", "knew_this")], {}, {"economics": 0.0}, REFS, NOW)
    p0 = model.prior(0.0, 0.5)
    edge = out.edges["c_repo"]
    assert edge.alpha == pytest.approx(2 * p0 + 2.0)
    assert edge.beta == pytest.approx(2 * (1 - p0))
    assert out.theta["economics"] == pytest.approx(model.elo(0.0, 1.0, 0.5, 0.1))
    assert out.applied == ("e1",)


def test_explain_opened_then_helpful_adds_one_and_a_half_to_beta():
    out = apply_events([ev("e1", "explain_opened"), ev("e2", "explain_helpful")], {}, {}, REFS, NOW)
    p0 = model.prior(0.0, 0.5)
    assert out.edges["c_repo"].beta == pytest.approx(2 * (1 - p0) + 1.5)
    # Only explain_opened is a graded outcome.
    assert out.theta["economics"] == pytest.approx(model.elo(0.0, 0.0, 0.5, 0.1))


def test_duplicate_ids_in_a_batch_apply_once():
    out = apply_events([ev("e1", "knew_this"), ev("e1", "knew_this")], {}, {}, REFS, NOW)
    assert out.applied == ("e1",)
    assert out.ignored == ("e1",)
    assert len(out.edges["c_repo"].evidence) == 1


def test_unknown_concepts_and_report_wrong():
    out = apply_events(
        [
            ev("e1", "knew_this", cid="c_nope"),
            ev("e2", "report_wrong"),
            ev("e3", "knew_this", None),
        ],
        {},
        {},
        REFS,
        NOW,
    )
    assert out.ignored == ("e1", "e3")
    assert out.applied == ("e2",)
    assert out.edges == {} and out.theta == {}


def test_paragraph_dwell_counts_words_capped():
    out = apply_events(
        [
            ReaderEvent("d1", "paragraph_dwell", NOW, words=120, ms=30000),
            ReaderEvent("d2", "paragraph_dwell", NOW, words=10**6, ms=1),
        ],
        {},
        {},
        REFS,
        NOW,
    )
    assert out.words_read == 120 + 2000
    assert out.edges == {}


def test_dismissal_counts_for_offset_but_adds_no_evidence():
    out = apply_events([ev("e1", "annotation_dismissed"), ev("e2", "knew_this")], {}, {}, REFS, NOW)
    assert out.applied_types == ("annotation_dismissed", "knew_this")
    assert list(out.edges) == ["c_repo"]
    assert [e.type for e in out.edges["c_repo"].evidence] == ["knew_this"]


def test_text_search_on_an_unannotated_paragraph_moves_the_offset_only():
    out = apply_events(
        [
            ReaderEvent("t1", "text_searched", NOW, content_id="a1", paragraph_id="p4"),
            ReaderEvent("t2", "text_searched", NOW, content_id="a1"),  # neither: ignored
        ],
        {},
        {},
        REFS,
        NOW,
    )
    assert out.applied == ("t1",) and out.ignored == ("t2",)
    assert out.applied_types == ("text_searched",)
    assert out.edges == {} and out.theta == {}
    assert out.content_ids == frozenset({"a1"})


def test_repeat_dwell_events_with_zero_words_add_no_words():
    # The client sends a paragraph's words on its first dwell per page view only.
    out = apply_events(
        [
            ReaderEvent("d1", "paragraph_dwell", NOW, paragraph_id="p1", words=80, ms=9000),
            ReaderEvent("d2", "paragraph_dwell", NOW, paragraph_id="p1", words=0, ms=4000),
        ],
        {},
        {},
        REFS,
        NOW,
    )
    assert out.words_read == 80 and out.applied == ("d1", "d2")


def test_existing_edges_are_updated_not_replaced():
    edge = Edge(alpha=3.0, beta=1.0, last_seen=NOW, band="understands")
    out = apply_events([ev("e1", "text_searched")], {"c_repo": edge}, {}, REFS, NOW)
    assert (out.edges["c_repo"].alpha, out.edges["c_repo"].beta) == (3.0, 2.0)


def test_correction_is_strong_evidence_both_ways():
    known = correction(None, REFS["c_repo"], {}, True, NOW)
    unknown = correction(None, REFS["c_repo"], {}, False, NOW)
    p0 = model.prior(0.0, 0.5)
    assert known.alpha == pytest.approx(2 * p0 + 3.0)
    assert unknown.beta == pytest.approx(2 * (1 - p0) + 3.0)


# ---------------------------------------------------------------- profile


def test_summary_template_example_from_the_design():
    text = profile.summary_text({"finance": 0.6, "economics": -0.4}, ["software"], 6)
    assert text == (
        "Comfortable in finance, building in economics. You think in software. "
        "6 concepts moved up a band this week."
    )


def test_summary_groups_levels_and_is_deterministic():
    theta = {"policy": -1.5, "business": 1.0, "finance": 0.2, "economics": 0.0}
    a = profile.summary_text(theta, ["software", "cricket"], 1)
    b = profile.summary_text(dict(reversed(list(theta.items()))), ["cricket", "software"], 1)
    assert (
        a
        == b
        == (
            "Advanced in business, comfortable in economics and finance, new to policy. "
            "You think in cricket and software. 1 concept moved up a band this week."
        )
    )


def test_summary_omits_empty_parts():
    assert profile.summary_text({"finance": -0.2}, [], 0) == "Building in finance."


@pytest.mark.parametrize(
    ("theta", "word"),
    [(1.0, "advanced"), (0.99, "comfortable"), (0.0, "comfortable"), (-0.01, "building"),
     (-1.0, "building"), (-1.01, "new to")],
)  # fmt: skip
def test_theta_words(theta, word):
    assert profile.theta_word(theta) == word


def test_moved_up_this_week():
    def e(prev, band, days):
        return Edge(1, 1, NOW, band, band_prev=prev, band_changed_at=NOW - timedelta(days=days))

    edges = {
        "up": e("heard of", "understands", 1),
        "down": e("understands", "heard of", 1),
        "old": e("unaware", "heard of", 8),
        "never": Edge(1, 1, NOW, "heard of"),
    }
    moves = profile.moved_up_this_week(edges, NOW)
    assert [(m.concept_id, m.from_band, m.to_band) for m in moves] == [
        ("up", "heard of", "understands")
    ]


def test_trend_skips_weeks_without_reading():
    trend = profile.annotation_trend(
        {
            "2026-W41": {"words_read": 2000, "annotations_shown": 10},
            "2026-W40": {"words_read": 1000, "annotations_shown": 14},
            "2026-W39": {"annotations_shown": 5},
        }
    )
    assert trend == [("2026-W40", 14.0), ("2026-W41", 5.0)]


def test_iso_week():
    assert profile.iso_week(datetime(2026, 10, 7, tzinfo=UTC)) == "2026-W41"


# ---------------------------------------------------------------- subgraph


def _concept(cid, prereqs=(), domain="economics", freq=0, label=None):
    return Concept(
        id=cid,
        label=label or cid,
        domain=domain,
        definition="d",
        base_difficulty=0.0,
        prerequisites=list(prereqs),
        doc_freq=freq,
        embedding=[1.0, 0.0],
    )


def _wide_graph() -> ConceptGraph:
    """100 leaves in economics, each with 3 prerequisites drawn from a 50-node base layer."""
    base = [_concept(f"c_base_{i}", domain="finance", freq=i) for i in range(50)]
    leaves = [
        _concept(f"c_leaf_{i}", prereqs=[f"c_base_{i % 50}", f"c_base_{(i + 7) % 50}",
                                         f"c_base_{(i + 19) % 50}"], freq=100 - i)
        for i in range(100)
    ]  # fmt: skip
    return ConceptGraph(ConceptGraphFile(version="t", concepts=base + leaves))


def _band(_c):
    return "heard of"


def _knows(ids):
    return {
        cid: Edge(2, 1, NOW - timedelta(days=i), "understands",
                  evidence=(model.Evidence("knew_this", 2.0, NOW),) * 3)
        for i, cid in enumerate(ids)
    }  # fmt: skip


def _check(sub):
    ids = {n.id for n in sub.nodes}
    assert len(sub.nodes) <= MAX_NODES
    assert len(ids) == len(sub.nodes)
    assert all(a in ids and b in ids for a, b in sub.edges)
    g = nx.DiGraph(sub.edges)
    g.add_nodes_from(ids)
    assert nx.is_directed_acyclic_graph(g)


def test_subgraph_never_exceeds_60_nodes_and_is_closed_and_acyclic():
    graph = _wide_graph()
    knows = _knows([f"c_leaf_{i}" for i in range(100)])
    sub = knowledge_subgraph(graph, knows, _band, NOW, domain="economics")
    _check(sub)
    assert sub.truncated
    assert len(sub.nodes) == MAX_NODES
    # The 40 most relevant leaves come first (most recent evidence = highest relevance).
    assert [n.id for n in sub.nodes[:3]] == ["c_leaf_0", "c_leaf_1", "c_leaf_2"]
    assert sum(n.id.startswith("c_leaf") for n in sub.nodes) == 40


def test_new_reader_sees_the_domains_most_frequent_concepts():
    sub = knowledge_subgraph(_wide_graph(), {}, _band, NOW, domain="economics")
    _check(sub)
    leaves = [n.id for n in sub.nodes if n.id.startswith("c_leaf")]
    assert leaves[:2] == ["c_leaf_0", "c_leaf_1"]  # doc_freq 100, 99
    assert len(leaves) == 20


def test_depth_puts_foundations_at_zero():
    graph = ConceptGraph(
        ConceptGraphFile(
            version="t",
            concepts=[
                _concept("c_a"),
                _concept("c_b", ["c_a"]),
                _concept("c_c", ["c_b", "c_a"]),
            ],
        )
    )
    sub = knowledge_subgraph(graph, _knows(["c_c"]), _band, NOW, domain="economics")
    _check(sub)
    assert {n.id: n.depth for n in sub.nodes} == {"c_a": 0, "c_b": 1, "c_c": 2}
    assert sub.edges == [("c_a", "c_b"), ("c_a", "c_c"), ("c_b", "c_c")]
    assert not sub.truncated
    node_c = next(n for n in sub.nodes if n.id == "c_c")
    assert node_c.evidence_count == 3


def test_search_returns_matches_with_their_prerequisite_chains():
    graph = ConceptGraph(
        ConceptGraphFile(
            version="t",
            concepts=[
                _concept("c_rate", label="Interest rate"),
                _concept("c_repo", ["c_rate"], label="Repo rate"),
                _concept("c_gdp", label="GDP"),
            ],
        )
    )
    sub = knowledge_subgraph(graph, {}, _band, NOW, domain="economics", q="repo")
    _check(sub)
    assert [n.id for n in sub.nodes] == ["c_repo", "c_rate"]
    assert sub.edges == [("c_rate", "c_repo")]
