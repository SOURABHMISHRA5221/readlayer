from app.graph.graph import ConceptGraph
from app.graph.models import Concept, ConceptGraphFile
from scripts.build_compare import classify_unlinked


def graph() -> ConceptGraph:
    c = Concept(
        id="c_hedge_fund",
        label="Hedge fund",
        domain="finance",
        definition="A pooled investment fund.",
        base_difficulty=0.5,
        embedding=[1.0, 0.0],
    )
    return ConceptGraph(ConceptGraphFile(version="t", concepts=[c]))


FATES = {
    "hedge fund": "kept as c_hedge_fund",
    "growth": "dropped: kind generic",
    "front end load": "dropped: single doc, specialization 1 (kind jargon)",
}


def test_dropped_candidates_report_their_reason():
    g = graph()
    assert classify_unlinked("Growth", g, FATES, {}, 0.87) == "dropped: kind generic"
    assert classify_unlinked("Front-end load", g, FATES, {}, 0.87).startswith("dropped: single doc")
    assert classify_unlinked("De facto", g, FATES, {}, 0.87) == "not a candidate"


def test_kept_concept_splits_floor_from_model_refusal():
    g = graph()
    below = classify_unlinked("Hedge funds", g, FATES, {"Hedge funds": [0.5, 0.866]}, 0.87)
    above = classify_unlinked("Hedge funds", g, FATES, {"Hedge funds": [1.0, 0.0]}, 0.87)
    assert "below floor" in below
    assert "model chose none" in above
