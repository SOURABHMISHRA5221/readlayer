"""Readiness on For you (decision 60, plan docs/plans/readiness.md): from the reader's own map."""

from app.graph.graph import ConceptGraph
from app.graph.models import ConceptGraphFile
from app.recs import feed_rank as fr
from app.recs.feed_router import _out
from tests.test_feed_rank import GRAPH, NOW, concept, reader, result

# b: base difficulty. At θ 0 a concept with b ≥ 0 is new (p < 0.5), with b < 0 known.
PRE = ConceptGraph(ConceptGraphFile(version="t", concepts=[
    concept("c_money", "Money", "economics", b=-2.0),                  # known
    concept("c_interest", "Interest rate", "economics", b=0.5),        # new, basic
    concept("c_bond", "Bond", "economics", b=1.0),                     # new
    concept("c_yield", "Bond yield", "economics", b=1.5),              # new
    concept("c_curve", "Yield curve", "economics", b=1.8),             # new
    concept("c_inverted", "Inverted yield curve", "economics", b=2.0),  # new
    concept("c_cash", "Cash", "economics", b=1.0),                     # new, no prerequisites
]))  # fmt: skip
PREREQS = {
    "c_bond": ["c_money", "c_interest"],
    "c_yield": ["c_bond", "c_interest"],
    "c_curve": ["c_yield", "c_interest", "c_missing"],
    "c_inverted": ["c_curve"],
}
PRE = ConceptGraph(ConceptGraphFile(version="t", concepts=[
    c.model_copy(update={"prerequisites": PREREQS.get(c.id, [])}) for c in PRE.concepts
]))  # fmt: skip


def item(text, topic="economics"):
    return fr.FeedCandidate(result(text, url=f"https://x.test/{abs(hash(text))}"), topic,
                            fr.named_concepts(PRE, text))  # fmt: skip


def ranked(text, **kw):
    return fr.rank([item(text)], reader(interest={"economics": 1.0}, **kw), NOW, PRE)[0]


def test_new_ideas_whose_groundwork_is_known_are_ready():
    r = ranked("Cash")  # new, no prerequisites in the graph: ready (the map shows no ring)
    assert r.readiness == "ready" and r.read_first == ()


def test_a_new_prerequisite_is_listed_most_basic_first_and_capped():
    r = ranked("Inverted yield curve")
    assert r.readiness == "stretch"
    assert r.read_first == ("Yield curve",)
    r = ranked("Yield curve")  # prerequisites Bond yield and Interest rate are both new
    assert r.read_first == ("Interest rate", "Bond yield")  # most basic (b) first, at most 2
    assert len(fr.read_first(list(item("Yield curve").concepts), frozenset(), PRE,
                             reader().state, NOW)) <= fr.READ_FIRST_MAX  # fmt: skip


def test_a_prerequisite_the_item_names_itself_is_not_listed_but_still_counts():
    r = ranked("Bond and Interest rate")
    assert r.new_concepts == ("Bond", "Interest rate")
    assert r.read_first == () and r.readiness == "ready"


def test_a_known_prerequisite_is_never_listed_and_a_missing_id_is_harmless():
    assert ranked("Bond").read_first == ("Interest rate",)  # Money is known
    assert "c_missing" in PREREQS["c_curve"] and ranked("Yield curve").readiness == "stretch"


def test_levels():
    assert fr.readiness_level(0, 0, ()) is None  # names nothing: no line, we know nothing
    assert fr.readiness_level(2, 0, ()) == "familiar"
    assert fr.readiness_level(2, 1, ()) == fr.readiness_level(5, 4, ()) == "ready"
    assert fr.readiness_level(6, 5, ()) == "stretch"  # many new ideas at once
    assert fr.readiness_level(1, 1, ("Bond",)) == "stretch"


def test_an_item_that_names_no_concept_has_no_level():
    r = fr.rank([fr.FeedCandidate(result("Markets today"), "economics", ())],
                reader(interest={"economics": 1.0}), NOW, PRE)[0]  # fmt: skip
    assert r.readiness is None and r.read_first == ()


def test_known_ideas_only_are_mostly_familiar():
    assert ranked("Money").readiness == "familiar"


def test_ranking_scores_are_unchanged():
    c = fr.FeedCandidate(result("Offside and VAR", url="https://x.test/a"), "sports",
                         fr.named_concepts(GRAPH, "Offside and VAR"))  # fmt: skip
    assert fr.rank([c], reader(), NOW, GRAPH)[0].score == 0.85  # pinned before the change


def test_select_and_the_route_model_carry_both_fields():
    picked = fr.select(fr.rank([item("Inverted yield curve")], reader(interest={"economics": 1.0}),
                               NOW, PRE), ["economics"])  # fmt: skip
    out = _out(picked[0])
    assert out.readiness == "stretch" and out.read_first == ["Yield curve"]
    none = _out(fr.rank([fr.FeedCandidate(result("Markets"), "economics", ())],
                        reader(interest={"economics": 1.0}), NOW, PRE)[0])  # fmt: skip
    assert none.readiness is None and none.read_first == []
