"""Glossary seeding, pure parts (M2.2 plan §B.3)."""

from app.graph.enrich import ConceptInfo
from app.graph.graph import ConceptGraph
from app.graph.models import Concept, ConceptGraphFile
from scripts import seed_glossaries as sg

WRAP = '<html><body><div class="mw-parser-output"><dl>{}</dl></div></body></html>'


def _graph() -> ConceptGraph:
    return ConceptGraph(ConceptGraphFile(version="t", concepts=[
        Concept(id="c_inflation", label="Inflation", domain="economics", definition="d.",
                base_difficulty=0.0, embedding=[1.0, 0.0]),
        Concept(id="c_goal", label="Goal", domain="sports", definition="d.",
                base_difficulty=0.0, embedding=[0.0, 1.0]),
    ]))  # fmt: skip


def _page(*terms: str) -> bytes:
    return WRAP.format("".join(f"<dt>{t}</dt><dd>Defined here.</dd>" for t in terms)).encode()


def test_collect_drops_existing_and_duplicate_terms_and_ranks_by_frequency(monkeypatch):
    monkeypatch.setattr(sg, "SEED_PER_DOMAIN", 2)
    sources = {"sports": ["Glossary_a", "Glossary_b"]}
    pages = {
        "Glossary_a": _page("goal", "offside", "zzyzx"),
        "Glossary_b": _page("Offside", "penalty"),
    }
    ranked, counts = sg.collect(sources, pages, _graph())
    labels = [c.label for c in ranked["sports"]]
    assert "Goal" not in labels  # exact match of an existing concept
    assert labels == sorted(labels, key=lambda x: -sg.zipf_frequency(x, "en"))[:2]
    assert len(labels) == 2 and "Zzyzx" not in labels  # rarest term ranked out
    c = counts["sports"]
    assert (c.pages, c.parsed, c.exact_existing, c.duplicates, c.ranked_out) == (2, 5, 1, 1, 1)


def test_new_concepts_get_ids_that_never_clash_with_the_graph():
    graph = _graph()
    cand = sg.Candidate("Inflation", [], "s", "economics", "Glossary_x", zipf=5.0)
    info = ConceptInfo(id=0, definition="A different sense, long enough.", specialization=2,
                       domain="economics", kind="idea", jurisdiction="global")  # fmt: skip
    (concept,) = sg.new_concepts([(cand, info)], graph, [[0.5, 0.5]])
    assert concept.id == "c_inflation_2" and concept.kind == "idea" and concept.doc_freq == 0
