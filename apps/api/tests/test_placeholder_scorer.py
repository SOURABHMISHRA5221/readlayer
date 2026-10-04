import math

import pytest

from app.graph.graph import ConceptGraph
from app.graph.models import Concept, ConceptGraphFile
from app.ingest.models import Anchor, ContentDoc, Demand, StoredParagraph
from app.scoring import placeholder as ps


def concept(cid, domain, b, prereqs=()):
    return Concept(
        id=cid,
        label=cid.removeprefix("c_").replace("_", " ").title(),
        domain=domain,
        definition=f"Definition of {cid}.",
        base_difficulty=b,
        prerequisites=list(prereqs),
        embedding=[1.0, 0.0],
    )


GRAPH = ConceptGraph(
    ConceptGraphFile(
        version="t",
        concepts=[
            concept("c_inflation", "economics", -1.0),
            concept("c_bond", "finance", 0.0),
            concept("c_yield_curve", "finance", 1.0, prereqs=["c_bond"]),
            concept("c_fiscal_deficit", "policy", 1.0, prereqs=["c_inflation"]),
            concept("c_monetary_policy", "economics", 1.0, prereqs=["c_inflation"]),
            concept("c_ebitda", "business", 1.0),
        ],
    )
)


def demand(
    did, target, pid="p0", start=0, type_="concept", salience=1.0, explained=False, zipf=3.0
):
    exact = (target or did).removeprefix("c_")
    return Demand(
        id=did,
        paragraph_id=pid,
        anchor=Anchor(exact=exact, prefix="", suffix="", start=start, end=start + len(exact)),
        type=type_,
        label=exact,
        target_id=target,
        salience=salience,
        explained_in_text=explained,
        zipf=zipf,
    )


def doc(demands, paragraphs=None, words=400):
    paragraphs = paragraphs or [StoredParagraph(id="p0", text="w " * words, structure=0.0)]
    return ContentDoc(
        content_id="x",
        url="u",
        final_url="u",
        title="t",
        site="s",
        source="fetch",
        fetched_at="now",
        paragraphs=paragraphs,
        demands=demands,
        demands_dropped=0,
        llm_calls=[],
    )


def paras(n, words=100):
    return [StoredParagraph(id=f"p{i}", text="w " * words, structure=0.0) for i in range(n)]


def test_prior_is_irt_logistic():
    assert ps.prior(0.0, 0.0) == pytest.approx(0.5)
    assert ps.prior(1.0, -1.0) == pytest.approx(1 / (1 + math.exp(-2)))


def test_concept_p_know_is_capped_by_best_prerequisite():
    theta = {"finance": 2.0, "economics": 0.0}
    d = demand("d1", "c_yield_curve")
    # own prior σ(2-1)=0.731; prereq bond σ(2-0)=0.881 + 0.1 → no cap
    assert ps.p_know(d, GRAPH.get("c_yield_curve"), GRAPH, theta) == pytest.approx(ps.sigmoid(1))
    # policy θ high, but prerequisite inflation known only at σ(-2+1)=0.269 → capped at 0.369
    theta = {"policy": 3.0, "economics": -2.0}
    d = demand("d2", "c_fiscal_deficit")
    got = ps.p_know(d, GRAPH.get("c_fiscal_deficit"), GRAPH, theta)
    assert got == pytest.approx(ps.sigmoid(-1) + 0.1)


def test_term_and_context_p_know():
    c = GRAPH.get("c_bond")
    term = demand("d1", "c_bond", type_="term", zipf=4.0)
    tau = 3.5 - 0.4 * 1.0
    assert ps.p_know(term, c, GRAPH, {"finance": 1.0}) == pytest.approx(ps.sigmoid(1.2 * (4 - tau)))
    ctx = demand("d2", "c_bond", type_="context")
    assert ps.p_know(ctx, c, GRAPH, {"finance": 5.0}) == pytest.approx(0.2)


def test_span_score_discounts_explained_in_text():
    assert ps.span_score(demand("a", "c_bond", salience=0.5), 0.2) == pytest.approx(0.4)
    explained = demand("a", "c_bond", salience=0.5, explained=True)
    assert ps.span_score(explained, 0.2) == pytest.approx(0.16)


def test_only_linked_demands_and_first_occurrence():
    demands = [
        demand("d2", "c_ebitda", start=50),
        demand("d1", "c_ebitda", start=10, salience=0.6),
        demand("d3", None, start=20, type_="term"),
    ]
    got = ps.annotate(doc(demands), GRAPH, {}, 0.0)
    assert [a.demand_id for a in got] == ["d1"]


def test_budget_one_per_80_words():
    demands = [demand(f"d{i}", c.id, start=i) for i, c in enumerate(GRAPH.concepts)]
    ps_paras = [StoredParagraph(id="p0", text="w " * 160, structure=0.0)]
    got = ps.annotate(doc(demands, ps_paras), GRAPH, {}, 0.0)
    # 160 words → 2 spans, but also ≤ 2 per paragraph
    assert len(got) == 2
    assert len(ps.annotate(doc(demands, paras(1, 10)), GRAPH, {}, 0.0)) == 1  # floor, min 1


def test_at_most_two_per_paragraph_and_ranked():
    demands = [
        demand("a", "c_ebitda", pid="p0", start=0, salience=0.9),
        demand("b", "c_bond", pid="p0", start=1, salience=0.8),
        demand("c", "c_inflation", pid="p0", start=2, salience=1.0),
        demand("d", "c_yield_curve", pid="p1", start=300, salience=0.5),
    ]
    got = ps.annotate(doc(demands, paras(2, 400)), GRAPH, {}, 0.0)
    assert [a.demand_id for a in got] == ["a", "b", "d"]
    assert [a.score for a in got] == sorted((a.score for a in got), reverse=True)


@pytest.mark.parametrize(
    ("density", "expected"),
    [("minimal", {"a"}), ("balanced", {"a", "b"}), ("guided", {"a", "b", "c"})],
)
def test_density_thresholds(density, expected):
    # θ=0 everywhere: b=1 → p≈0.269 (miss≈0.731); b=0 → p=0.5
    demands = [
        demand("a", "c_ebitda", pid="p0", salience=1.0),  # 0.731
        demand("b", "c_monetary_policy", pid="p1", salience=0.75),  # 0.548
        demand("c", "c_bond", pid="p2", salience=0.7),  # 0.35
    ]
    got = ps.annotate(doc(demands, paras(3, 400)), GRAPH, {}, ps.DENSITY_THRESHOLDS[density])
    assert {a.demand_id for a in got} == expected


def test_card_fields_and_determinism():
    d = doc([demand("a", "c_yield_curve")])
    first = ps.annotate(d, GRAPH, {}, 0.0)
    assert first == ps.annotate(d, GRAPH, {}, 0.0)
    a = first[0]
    assert (a.label, a.prerequisites, a.domain) == ("Yield Curve", ("Bond",), "finance")
    assert a.definition == "Definition of c_yield_curve."


def test_personas_see_different_not_nested_sets():
    demands = [
        demand("fin", "c_yield_curve", pid="p0"),
        demand("pol", "c_fiscal_deficit", pid="p1"),
        demand("eco", "c_monetary_policy", pid="p2"),
        demand("biz", "c_ebitda", pid="p3"),
    ]
    article = doc(demands, paras(4, 400))
    sets = {
        k: {a.demand_id for a in ps.annotate(article, GRAPH, p.theta, 0.45)}
        for k, p in ps.PERSONAS.items()
    }
    trader, policy = sets["trader"], sets["policy_student"]
    assert trader - policy and policy - trader
    assert sets["newcomer"] >= trader | policy
