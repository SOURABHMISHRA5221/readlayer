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
