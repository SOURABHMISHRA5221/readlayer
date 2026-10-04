from scripts.add_doc_freq import doc_freq, with_doc_freq
from tests.test_recs_library import GRAPH, demand, doc


def test_doc_freq_counts_duplicate_groups_once():
    docs = [
        doc("a", "A", "s", [demand("d1", "c_bond"), demand("d2", "c_bond")]),
        doc("a_syndicated", "A", "s2", [demand("d1", "c_bond")]),
        doc("b", "B", "s", [demand("d1", "c_bond"), demand("d2", "c_repo")]),
    ]
    freq = doc_freq(docs, {"a": 0, "a_syndicated": 0, "b": 1})
    assert freq == {"c_bond": 2, "c_repo": 1}


def test_with_doc_freq_defaults_to_zero():
    from app.graph.models import ConceptGraphFile

    file = ConceptGraphFile(version="t", concepts=GRAPH.concepts)
    patched = with_doc_freq(file, {"c_bond": 4})
    assert {c.id: c.doc_freq for c in patched.concepts}["c_bond"] == 4
    assert {c.doc_freq for c in patched.concepts if c.id != "c_bond"} == {0}
