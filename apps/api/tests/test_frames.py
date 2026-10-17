"""Decision 67 A1–A2: the "for you" analogy frame, from the reader's own edges."""

from typing import get_args

from app.explain import service
from app.explain.models import BackgroundDraft, Card, Explanation
from app.graph.graph import ConceptGraph
from app.graph.models import ConceptGraphFile
from app.graph.taxonomy import DOMAIN_IDS
from app.reader import frames
from app.reader.state import THINKS_IN
from tests.test_scorer import NOW, concept, edge
from tests.test_scorer import state as scorer_state


def engaged(n: int) -> dict:
    return {f"content_{i}": NOW for i in range(n)}


def state(**kw):
    """A reader past decision 70's gate unless the test says otherwise."""
    return scorer_state(**{"engaged": engaged(frames.MIN_ARTICLES), **kw})


def _graph() -> ConceptGraph:
    cs = []
    for domain, n in (("finance", 4), ("economics", 4), ("technology", 3), ("health", 2)):
        cs += [concept(f"c_{domain}_{i}", domain, 0.0, ()) for i in range(n)]
    return ConceptGraph(ConceptGraphFile(version="fr", concepts=cs))


GRAPH = _graph()


def known(*ids: str, p: float = 0.9):
    return {cid: edge(p) for cid in ids}


def test_frames_cover_thinks_in_and_every_domain():
    assert set(THINKS_IN) <= set(frames.FRAMES)
    assert set(frames.DOMAIN_FRAME) == set(DOMAIN_IDS)
    assert frames.DOMAIN_FRAME["technology"] == "software"
    assert frames.DOMAIN_FRAME["health"] == "medicine"
    assert frames.DOMAIN_FRAME["finance"] == "finance"
    assert set(frames.DOMAIN_FRAME.values()) <= set(frames.FRAMES)


def test_strongest_domain_by_known_concepts_excluding_the_notes_own():
    st = state(edges={**known("c_finance_0", "c_finance_1", "c_finance_2", "c_finance_3"),
                      **known("c_economics_0", "c_economics_1", "c_economics_2")})  # fmt: skip
    assert frames.for_you(st, GRAPH, "law", NOW) == "finance"
    assert frames.for_you(st, GRAPH, "finance", NOW) == "economics"  # own domain explains nothing


def test_needs_three_known_and_ignores_weak_edges_and_the_prior():
    weak = known("c_economics_0", "c_economics_1", "c_economics_2", p=0.2)
    st = state(theta={"health": 3.0}, edges={**known("c_finance_0", "c_finance_1"), **weak})
    assert frames.for_you(st, GRAPH, None, NOW) is None


def test_ties_by_mean_p_then_taxonomy_order_and_mapping():
    tech = known("c_technology_0", "c_technology_1", "c_technology_2", p=0.95)
    st = state(edges={**known("c_finance_0", "c_finance_1", "c_finance_2", p=0.8), **tech})
    assert frames.for_you(st, GRAPH, None, NOW) == "software"  # technology, mapped
    even = state(edges={**known("c_finance_0", "c_finance_1", "c_finance_2"),
                        **known("c_economics_0", "c_economics_1", "c_economics_2")})  # fmt: skip
    assert frames.for_you(even, GRAPH, None, NOW) == "economics"  # taxonomy order


def test_for_you_needs_ten_engaged_articles():
    """Decision 70: the first map is mostly onboarding guesses, so no "for you" frame until the
    reader has engaged with 10 pieces."""
    edges = known("c_finance_0", "c_finance_1", "c_finance_2")
    assert frames.MIN_ARTICLES == 10
    assert frames.for_you(state(edges=edges, engaged=engaged(9)), GRAPH, None, NOW) is None
    assert frames.for_you(state(edges=edges, engaged=engaged(10)), GRAPH, None, NOW) == "finance"
    assert frames.for_you(state(edges=edges, engaged={}), GRAPH, None, NOW) is None


def test_unknown_concepts_in_edges_are_skipped():
    st = state(edges=known("c_gone_1", "c_gone_2", "c_gone_3"))
    assert frames.for_you(st, GRAPH, None, NOW) is None


def test_a_map_frame_is_a_valid_analogy_label_everywhere():
    for model in (BackgroundDraft, Explanation, Card):
        field = model.model_fields["analogy_domain"].annotation
        allowed = {a for arg in get_args(field) for a in (get_args(arg) or (arg,))}
        assert "finance" in allowed and "software" in allowed
    draft = BackgroundDraft(background="Like a hedge on a position.", analogy_domain="finance")
    assert draft.analogy_domain == "finance"


def test_prompt_versions_are_pinned_so_the_warm_cache_stays_valid():
    """Decision 67 A1a: widening the frame list must not change a prompt version (the cache
    keys hash them). Change these only with a planned re-warm."""
    assert service.restate_version() == "restate-v2+verify-v2"
    assert service.background_version() == "explain-v5+verify-background-v1"
    assert service.prompt_version() == "restate-v2+verify-v2|explain-v5+verify-background-v1"
