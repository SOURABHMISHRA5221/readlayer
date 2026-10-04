import networkx as nx
import numpy as np
import pytest

from app.graph.build import (
    Prereq,
    apply_keep,
    break_cycles,
    calibrate_threshold,
    candidate_pairs,
    clusters,
    difficulty,
    duplicate_pairs,
    jaccard,
    normalize_label,
    percentiles,
    prereq_digraph,
    shingles,
    slug_ids,
    validate_prereqs,
)


@pytest.mark.parametrize(
    ("raw", "key"),
    [
        ("Repo Rate", "repo rate"),
        ("repo rates", "repo rate"),
        ("Bond yields", "bond yield"),
        ("Yield (finance)", "yield"),
        ("Price–earnings ratio", "price earnings ratio"),
        ("price-earnings ratio", "price earnings ratio"),
        ("Subsidies", "subsidy"),
        ("Economics", "economics"),
        ("GST", "gst"),
        ("basis points", "basis point"),
        ("Purchasing Managers' Index", "purchasing managers index"),
        ("  ", ""),
    ],
)
def test_normalize_label(raw, key):
    assert normalize_label(raw) == key


def test_slug_ids_are_valid_and_unique():
    assert slug_ids(["Repo rate", "Repo-rate", "Café index", "!!!"]) == [
        "c_repo_rate",
        "c_repo_rate_2",
        "c_cafe_index",
        "c_concept",
    ]


def test_clusters_union_find():
    groups = clusters(5, [(0, 1), (1, 2), (3, 4)])
    assert sorted(sorted(g) for g in groups) == [[0, 1, 2], [3, 4]]
    assert clusters(3, []) == [[0], [1], [2]]


def unit(*rows):
    m = np.asarray(rows, dtype=float)
    return m / np.linalg.norm(m, axis=1, keepdims=True)


def test_candidate_pairs_band_and_top_k():
    v = unit([1, 0], [0.99, 0.14], [0.97, 0.24], [0, 1])
    above = candidate_pairs(v, 0.95, top_k=5)
    assert [(i, j) for i, j, _ in above] == [(0, 1), (0, 2), (1, 2)]
    assert [(i, j) for i, j, _ in candidate_pairs(v, 0.95, top_k=1)] == [(0, 1), (1, 2)]
    band = candidate_pairs(v, 0.0, high=0.95)
    assert all(s < 0.95 for *_, s in band) and (0, 3) in [(i, j) for i, j, _ in band]


def test_duplicate_pairs_need_text_overlap():
    story = "the reserve bank of india kept the repo rate unchanged at six percent on friday"
    rewrite = story + " analysts said"
    other = "sebi proposed new rules for the closing auction session in the cash market today"
    sets = [shingles(story), shingles(rewrite), shingles(other)]
    same_vectors = unit([1, 0], [1, 0], [1, 0])  # same topic embedding for all three
    pairs = duplicate_pairs(sets, same_vectors)
    assert [(p.a, p.b) for p in pairs] == [(0, 1)]
    assert jaccard(set(), {"a"}) == 0.0


def test_keep_rule():
    for kind in (
        "idea",
        "jargon",
        "institution",
        "regulator",
        "committee",
        "index",
        "tax",
        "policy",
        "scheme",
        "instrument",
        "entity_type",
        "market_event",
        "unit",
    ):
        assert apply_keep(kind)
    for kind in ("company", "person", "place", "event", "generic"):
        assert not apply_keep(kind)
    assert apply_keep("company", is_seed=True)


def test_single_doc_concepts_need_specialization_two():
    assert not apply_keep("jargon", doc_groups=1, specialization=1)
    assert apply_keep("jargon", doc_groups=1, specialization=2)
    assert apply_keep("idea", doc_groups=2, specialization=1)  # multi-doc: no floor
    assert apply_keep("generic", is_seed=True, doc_groups=1, specialization=1)
    assert not apply_keep("company", doc_groups=1, specialization=5)


def test_difficulty_mapping_and_clamp():
    assert difficulty(3, 4.0) == 0.0
    assert difficulty(1, 6.0) == -2.0
    assert difficulty(5, 1.0) == 2.0
    assert difficulty(4, 3.0) == pytest.approx(0.75 + 0.25)
    assert difficulty(9, 0.0) == 2.0


def test_validate_prereqs():
    proposed = [
        Prereq("c_a", 0.5),
        Prereq("c_self", 0.9),
        Prereq("c_x", 0.9),
        Prereq("c_b", 0.8),
        Prereq("c_c", 0.7),
        Prereq("c_d", 0.6),
        Prereq("c_b", 0.1),
    ]
    kept = validate_prereqs("c_self", proposed, {"c_a", "c_b", "c_c", "c_d", "c_self"})
    assert [p.id for p in kept] == ["c_b", "c_c", "c_d"]


def test_break_cycles_drops_least_confident_edge():
    edges = {
        "c_a": [Prereq("c_b", 0.9)],
        "c_b": [Prereq("c_c", 0.8)],
        "c_c": [Prereq("c_a", 0.3)],  # weakest edge in the cycle
        "c_d": [Prereq("c_a", 0.9)],
    }
    clean, removed = break_cycles(edges, {})
    assert removed == [("c_a", "c_c")]
    assert nx.is_directed_acyclic_graph(prereq_digraph(clean))
    assert clean["c_d"] == [Prereq("c_a", 0.9)]


def test_break_cycles_tie_prefers_dropping_harder_prereq():
    edges = {"c_easy": [Prereq("c_hard", 0.5)], "c_hard": [Prereq("c_easy", 0.5)]}
    _, removed = break_cycles(edges, {"c_easy": -1.0, "c_hard": 1.5})
    assert removed == [("c_hard", "c_easy")]


def test_calibrate_threshold_lowest_with_target_precision():
    pos = [0.70, 0.80, 0.85, 0.90, 0.95]
    neg = [0.50, 0.60, 0.72, 0.78]
    # t=0.80: 4 tp, 0 fp -> 1.0; t=0.78: 4 tp, 1 fp -> 0.8; t=0.72: 4 tp, 2 fp -> 0.67
    assert calibrate_threshold(pos, neg, 0.95) == 0.8
    assert calibrate_threshold(pos, neg, 0.75) == 0.78
    assert calibrate_threshold([0.5], [0.9], 0.95) is None


def test_percentiles():
    p = percentiles([float(i) for i in range(101)])
    assert p[5] == 5.0 and p[50] == 50.0 and p[95] == 95.0
    assert percentiles([]) == {}
