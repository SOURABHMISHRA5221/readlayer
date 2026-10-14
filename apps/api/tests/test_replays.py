"""M9 part 2 replay reports: pure, so the tables can be trusted."""

from scripts.replay_merges import Row, report


def test_merge_report_counts_false_merges_and_misses():
    rows = [
        Row("Forever chemicals", "PFAS", 0.899, "same", True),
        Row("PFAS", "PFOS", 0.971, "different", True),  # a false merge above the duplicate
        Row("Edge", "Node", 0.94, "different", False),
        Row("A", "B", 0.86, "same", False),  # a missed duplicate
    ]
    out = report(rows, 0.0123)
    assert "**4 pairs: false merges 1 (1 at cosine ≥ 0.899), missed duplicates 1.**" in out
    assert out.count("**disagree**") == 2 and "$0.0123" in out


def test_a_concept_is_never_its_own_prerequisite_candidate():
    from types import SimpleNamespace

    from scripts.replay_prereqs import pool_without

    pool = [SimpleNamespace(id="c_pfos"), SimpleNamespace(id="c_chemistry")]
    assert [c.id for c in pool_without(pool, "c_pfos")] == ["c_chemistry"]


def test_the_cut_drops_every_wrong_edge_and_keeps_90_percent_of_the_right():
    from scripts.replay_prereqs import Edge, choose

    right = [Edge(f"c{i}", "p", 0.6 + i / 100, True) for i in range(10)]
    wrong = [Edge("PFOS", "PHOSITA", 0.55, False)]
    t, n = choose(right + wrong)
    assert t == 0.6 and n["dropped_wrong"] == 1 and n["dropped_right"] == 0


def test_when_no_cut_does_both_it_keeps_90_percent_of_the_right():
    from scripts.replay_prereqs import Edge, choose

    right = [Edge(f"c{i}", "p", 0.5 + i / 100, True) for i in range(10)]
    wrong = [Edge("x", "y", 0.95, False)]  # more confident than every right edge
    t, n = choose(right + wrong)
    assert n["kept_wrong"] == 1 and n["dropped_right"] <= 1


def test_the_grown_sample_is_fixed_by_its_ids_and_seed():
    from scripts.sample_grown import sample

    ids = [f"c_{i}" for i in range(78)]
    first = sample(ids, 1015)
    assert len(first) == 30 and len(set(first)) == 30
    assert sample(list(reversed(ids)), 1015) == first  # order of the input doesn't matter
    assert sample(ids, 1016) != first
