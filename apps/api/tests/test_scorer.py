"""Gap scorer and annotation budget (DESIGN §5–6): pure, deterministic, every cap."""

import random
from datetime import UTC, datetime, timedelta

import pytest

from app.graph.graph import ConceptGraph
from app.graph.models import Concept, ConceptGraphFile
from app.ingest.models import Anchor, ContentDoc, Demand, StoredParagraph
from app.reader import events as reader_events
from app.reader import model
from app.reader.model import Edge, Evidence
from app.reader.personas import PERSONAS, build_template
from app.reader.state import ReaderState
from app.scoring import rules
from app.scoring import scorer as sc
from app.scoring.scorer import ExplainerRef, ScoringInputs

NOW = datetime(2026, 10, 8, 9, tzinfo=UTC)


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


def doc(demands, paragraphs=None, words=400, content_id="x"):
    paragraphs = paragraphs or [StoredParagraph(id="p0", text="w " * words, structure=0.0)]
    return ContentDoc(
        content_id=content_id,
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


def paras(n, words=100, structure=0.0):
    return [StoredParagraph(id=f"p{i}", text="w " * words, structure=structure) for i in range(n)]


def edge(p, conf=2.0, at=NOW, evidence=()):
    return Edge(
        alpha=p * conf,
        beta=(1 - p) * conf,
        last_seen=at,
        band=model.band_of(p),
        evidence=tuple(evidence),
    )


def state(theta=None, edges=None, offset=0.0, **kw):
    return ReaderState(theta=theta or {}, edges=edges or {}, threshold_offset=offset, **kw)


def annotate(article, st=None, density="balanced", inputs=None, graph=GRAPH):
    return sc.annotate(article, graph, st or state(), density, NOW, inputs)


def span_ids(result):
    return [s.demand_id for s in result.spans]


# ---------------------------------------------------------------- DESIGN §5 worked example


EXAMPLE_GRAPH = ConceptGraph(
    ConceptGraphFile(
        version="example",
        concepts=[
            concept("c_bond_yield", "finance", 0.0),
            concept("c_yield_curve", "finance", -0.7, prereqs=["c_bond_yield"]),
            concept("c_inflation", "economics", -1.5),
        ],
    )
)


def test_design_worked_example():
    """DESIGN §5 worked example: a reader new to markets, balanced density."""
    reader = state(
        theta={"finance": -0.5, "economics": -0.5},
        edges={
            "c_bond_yield": Edge(alpha=0.44, beta=1.56, last_seen=NOW, band="unaware"),
            "c_inflation": Edge(alpha=4.05, beta=0.95, last_seen=NOW, band="can explain"),
        },
    )
    article = doc(
        [
            demand("d17", "c_yield_curve", pid="p3", start=10, salience=1.0),
            demand("d18", "c_inflation", pid="p3", start=60, salience=1.0),
        ],
        [StoredParagraph(id="p3", text="w " * 120, structure=0.5)],
    )
    scored = {s.demand.id: s for s in sc.score_demands(article, EXAMPLE_GRAPH, reader, NOW,
                                                         ScoringInputs())}  # fmt: skip
    # yield curve: own prior σ(−0.5 + 0.7) = 0.550, capped by bond yield 0.22 + 0.1 = 0.32
    assert rules.concept_p(EXAMPLE_GRAPH.get("c_yield_curve"), reader, NOW) == pytest.approx(
        0.5498, abs=1e-4
    )
    assert scored["d17"].p_know == pytest.approx(0.32)
    assert scored["d17"].score == pytest.approx(0.68)
    # inflation: edge p_know 4.05 / 5 = 0.81 → 0.19
    assert scored["d18"].p_know == pytest.approx(0.81)
    assert scored["d18"].score == pytest.approx(0.19)

    result = sc.annotate(article, EXAMPLE_GRAPH, reader, "balanced", NOW)
    assert span_ids(result) == ["d17"]  # 0.68 ≥ 0.45 shown, 0.19 skipped
    # paragraph: 1 − 0.32·0.81 = 0.741 < 0.75 alone; + 0.3·0.5·(1 − σ(−0.5)) = 0.093 → 0.834
    spans_alone = 1 - 0.32 * 0.81
    assert spans_alone < rules.THRESHOLDS["balanced"]["paragraph"]
    assert [m.paragraph_id for m in result.paragraphs] == ["p3"]
    assert result.paragraphs[0].score == pytest.approx(0.8342, abs=1e-4)
    assert result.preread is None  # assumed mean (0.68 + 0.19) / 2 = 0.435 < 0.45
    assert result.prompt is None


# ---------------------------------------------------------------- rules


def test_concept_p_know_is_capped_by_best_prerequisite():
    reader = state({"finance": 2.0})
    d = demand("d1", "c_yield_curve")
    # own prior σ(2−1)=0.731; prereq bond σ(2−0)=0.881 + 0.1 → no cap
    got = rules.demand_p(d, GRAPH.get("c_yield_curve"), GRAPH, reader, NOW, None, ())
    assert got == pytest.approx(model.sigmoid(1))
    # policy θ high, but prerequisite inflation known only at σ(−2+1)=0.269 → capped at 0.369
    reader = state({"policy": 3.0, "economics": -2.0})
    got = rules.capped_concept_p(GRAPH.get("c_fiscal_deficit"), GRAPH, reader, NOW)
    assert got == pytest.approx(model.sigmoid(-1) + 0.1)


def test_edge_beats_prior_and_forgetting_pulls_back_to_it():
    c = GRAPH.get("c_ebitda")  # θ 0, b 1 → prior 0.269
    p0 = model.prior(0.0, 1.0)
    fresh = state(edges={"c_ebitda": edge(0.9, conf=6.0)})
    assert rules.concept_p(c, fresh, NOW) == pytest.approx(0.9)
    stale = state(edges={"c_ebitda": edge(0.9, conf=6.0, at=NOW - timedelta(days=90))})
    # 90 days: α and β each halve their distance to the prior's pseudo-counts
    alpha = 2 * p0 + 0.5 * (5.4 - 2 * p0)
    beta = 2 * (1 - p0) + 0.5 * (0.6 - 2 * (1 - p0))
    assert rules.concept_p(c, stale, NOW) == pytest.approx(alpha / (alpha + beta))
    assert rules.concept_p(c, state(), NOW) == pytest.approx(p0)


def test_term_rule_uses_domain_theta():
    c = GRAPH.get("c_bond")
    term = demand("d1", "c_bond", type_="term", zipf=4.0)
    tau = 3.5 - 0.4 * 1.0
    got = rules.demand_p(term, c, GRAPH, state({"finance": 1.0}), NOW, None, ())
    assert got == pytest.approx(model.sigmoid(1.2 * (4 - tau)))
    unlinked = demand("d2", None, type_="term", zipf=4.0)
    got = rules.demand_p(unlinked, None, GRAPH, state({"finance": 1.0}), NOW, "finance", ())
    assert got == pytest.approx(model.sigmoid(1.2 * (4 - tau)))


def test_context_rule_needs_recent_engagement():
    ctx = demand("d2", None, type_="context")
    key = rules.entity_key(ctx)
    assert rules.demand_p(ctx, None, GRAPH, state(), NOW, None, ()) == 0.2
    assert rules.demand_p(ctx, None, GRAPH, state(), NOW, None, {key}) == 0.8


def test_linked_context_reference_counts_what_the_reader_knows():
    ctx = demand("d2", "c_bond", type_="context")
    bond = GRAPH.get("c_bond")
    knows = state(edges={"c_bond": edge(0.9, conf=6.0)})
    assert rules.demand_p(ctx, bond, GRAPH, knows, NOW, None, ()) == pytest.approx(0.9)
    # an edge counts even when it says "doesn't know": 0.2 floor, edge 0.1
    gap = state(edges={"c_bond": edge(0.1, conf=3.0)})
    assert rules.demand_p(ctx, bond, GRAPH, gap, NOW, None, ()) == 0.2
    # no edge: a confident prior counts (σ(2) = 0.88), a coin-flip prior doesn't (σ(0.1))
    sure = rules.demand_p(ctx, bond, GRAPH, state({"finance": 2.0}), NOW, None, ())
    assert sure == pytest.approx(model.sigmoid(2.0))
    assert rules.demand_p(ctx, bond, GRAPH, state({"finance": 0.1}), NOW, None, ()) == 0.2
    assert rules.demand_p(ctx, bond, GRAPH, state({"finance": -3.0}), NOW, None, ()) == 0.2


def test_engaged_entities_come_from_recent_other_contents():
    other = doc([demand("o1", None, type_="context")], content_id="other")
    old = doc([demand("o2", "c_bond", type_="context")], content_id="old")
    reader = state(engaged={"other": NOW - timedelta(days=3), "old": NOW - timedelta(days=40)})
    by_id = {"other": other, "old": old}
    got = sc.engaged_entities(by_id, reader.recent_contents(NOW), exclude="x")
    assert got == {rules.entity_key(other.demands[0])}
    assert sc.engaged_entities(by_id, ["other"], exclude="other") == frozenset()


def test_unlinked_concepts_are_not_scored():
    assert rules.demand_p(demand("d", None), None, GRAPH, state(), NOW, None, ()) is None


def test_span_score_discounts_explained_in_text():
    assert rules.span_score(0.2, 0.5, False) == pytest.approx(0.4)
    assert rules.span_score(0.2, 0.5, True) == pytest.approx(0.16)


def test_paragraph_noisy_or_and_clip():
    assert rules.paragraph_score([0.5, 0.5], 0.0, 0.0) == pytest.approx(0.75)
    assert rules.paragraph_score([], 1.0, 0.0) == pytest.approx(0.15)
    assert rules.paragraph_score([0.99, 0.99], 1.0, -5.0) == 1.0


def test_threshold_offset_adapts_and_clamps():
    assert rules.next_offset(0.0, ["knew_this", "annotation_dismissed"]) == pytest.approx(0.04)
    assert rules.next_offset(0.0, ["text_searched"]) == pytest.approx(-0.02)
    assert rules.next_offset(0.0, ["explain_opened", "paragraph_dwell"]) == 0.0
    assert rules.next_offset(0.14, ["knew_this"] * 5) == pytest.approx(0.15)
    assert rules.next_offset(-0.14, ["text_searched"] * 5) == pytest.approx(-0.15)
    assert rules.threshold("balanced", "span", 0.5) == pytest.approx(0.60)


# ---------------------------------------------------------------- selection and caps


def test_only_linked_demands_and_first_occurrence():
    demands = [
        demand("d2", "c_ebitda", start=50),
        demand("d1", "c_ebitda", start=10, salience=0.6),
        demand("d3", None, start=20, type_="term"),
    ]
    assert span_ids(annotate(doc(demands), density="guided")) == ["d1"]


def test_budget_one_span_per_80_words():
    demands = [demand(f"d{i}", c.id, pid=f"p{i}", start=i) for i, c in enumerate(GRAPH.concepts)]
    article = doc(demands, paras(6, 40))  # 240 words → 3 spans
    assert len(annotate(article, density="guided").spans) == 3
    tiny = doc(demands, paras(6, 5))  # 30 words → floor 0, but at least 1
    assert len(annotate(tiny, density="guided").spans) == 1


def test_at_most_two_spans_per_paragraph_and_ranked():
    demands = [
        demand("a", "c_ebitda", pid="p0", start=0, salience=0.9),
        demand("b", "c_yield_curve", pid="p0", start=1, salience=0.8),
        demand("c", "c_monetary_policy", pid="p0", start=2, salience=1.0),
        demand("d", "c_fiscal_deficit", pid="p1", start=300, salience=0.5),
    ]
    got = annotate(doc(demands, paras(2, 400)), density="guided").spans
    assert [a.demand_id for a in got] == ["c", "a", "d"]
    assert [a.score for a in got] == sorted((a.score for a in got), reverse=True)


def test_paragraph_markers_one_per_three_paragraphs():
    demands = [demand(f"d{i}", "c_ebitda", pid=f"p{i}", start=i * 100) for i in range(6)]
    article = doc(demands, paras(6, 100, structure=1.0))
    got = annotate(article, density="guided").paragraphs
    assert len(got) == 2  # 6 paragraphs → 2 markers
    assert [m.paragraph_id for m in got] == ["p0", "p1"]  # equal scores → reading order


@pytest.mark.parametrize(
    ("density", "expected"),
    [("minimal", {"a"}), ("balanced", {"a", "b"}), ("guided", {"a", "b", "c"})],
)
def test_density_thresholds(density, expected):
    # θ = 0: b=1 → p≈0.269 (miss≈0.731); b=0 → p=0.5
    demands = [
        demand("a", "c_ebitda", pid="p0", salience=1.0),  # 0.731
        demand("b", "c_monetary_policy", pid="p1", salience=0.75),  # 0.548 (cap 0.731+0.1)
        demand("c", "c_bond", pid="p2", salience=0.7),  # 0.35
    ]
    got = annotate(doc(demands, paras(3, 400)), density=density)
    assert set(span_ids(got)) == expected


def test_positive_offset_hides_borderline_spans():
    demands = [demand("b", "c_monetary_policy", pid="p1", salience=0.75)]  # 0.548
    article = doc(demands, paras(2, 400))
    assert span_ids(annotate(article, state(offset=0.0))) == ["b"]
    assert span_ids(annotate(article, state(offset=0.15))) == []
    assert span_ids(annotate(article, state(offset=0.9))) == []  # clamped, still hidden


def test_knew_this_suppresses_until_contrary_explicit_evidence():
    article = doc([demand("a", "c_ebitda")])
    knew = Evidence("knew_this", 2.0, NOW)
    # a confident gap edge that one knew_this doesn't lift above the threshold
    gap = Edge(alpha=0.45 + 2.0, beta=2.55, last_seen=NOW, band="heard of", evidence=(knew,))
    assert (
        sc.select_spans(
            sc.first_occurrences(sc.score_demands(article, GRAPH, state(), NOW, ScoringInputs())),
            state(edges={"c_ebitda": gap}),
            400,
            0.45,
        )
        == []
    )
    assert span_ids(annotate(article, state(edges={"c_ebitda": gap}))) == []
    reopened = Edge(**(vars(gap) | {"evidence": (knew, Evidence("explain_opened", -1.0, NOW))}))
    assert span_ids(annotate(article, state(edges={"c_ebitda": reopened}))) == ["a"]


def test_same_input_same_output_regardless_of_demand_order():
    demands = [
        demand(f"d{i}", c.id, pid=f"p{i % 3}", start=i * 7, salience=0.5 + i / 20)
        for i, c in enumerate(GRAPH.concepts)
    ]
    article = doc(demands, paras(3, 200, structure=0.4))
    reader = state({"finance": 0.4, "policy": -0.3}, {"c_bond": edge(0.3)})
    first = annotate(article, reader, density="guided")
    for seed in range(5):
        shuffled = demands[:]
        random.Random(seed).shuffle(shuffled)
        assert annotate(doc(shuffled, paras(3, 200, structure=0.4)), reader, "guided") == first
    assert first.spans and first.paragraphs


def test_card_fields():
    a = annotate(doc([demand("a", "c_yield_curve")])).spans[0]
    assert (a.label, a.prerequisites, a.domain) == ("Yield Curve", ("Bond",), "finance")
    assert a.definition == "Definition of c_yield_curve."


# ---------------------------------------------------------------- uncertainty prompt


def test_prompt_picks_an_unannotated_uncertain_salient_concept():
    # bond: θ 0, b 0 → p 0.5, confidence 2; span 0.5·0.8 = 0.4 < 0.45, so not a span
    demands = [
        demand("a", "c_ebitda", pid="p0", salience=1.0),  # span
        demand("b", "c_bond", pid="p1", start=100, salience=0.8),
        demand("c", "c_inflation", pid="p1", start=120, salience=0.9),  # p 0.73: out of range
    ]
    got = annotate(doc(demands, paras(2, 200)))
    assert span_ids(got) == ["a"]
    assert got.prompt is not None and got.prompt.concept_id == "c_bond"


@pytest.mark.parametrize("known", [False, True])
def test_a_know_this_answer_turns_the_prompt_into_a_span_or_nothing(known):
    """Decision 46d: after "Not really" the refetched notes carry the term as a span; after "Yes"
    it is neither a span nor the prompt (the same correction PATCH /v1/me/graph applies)."""
    demands = [
        demand("a", "c_ebitda", pid="p0", salience=1.0),
        demand("b", "c_bond", pid="p1", start=100, salience=0.8),
        demand("c", "c_inflation", pid="p1", start=120, salience=0.9),
    ]
    article = doc(demands, paras(2, 200))
    before = annotate(article)
    assert before.prompt is not None and before.prompt.concept_id == "c_bond"
    assert "b" not in span_ids(before)
    bond = GRAPH.get("c_bond")
    ref = reader_events.ConceptRef(domain=bond.domain, difficulty=bond.base_difficulty)
    answered = state(edges={"c_bond": reader_events.correction(None, ref, {}, known, NOW)})
    after = annotate(article, answered)
    assert ("b" in span_ids(after)) is (not known)
    assert after.prompt is None or after.prompt.concept_id != "c_bond"


@pytest.mark.parametrize(
    "reader",
    [
        state(edges={"c_bond": edge(0.5, conf=4.0)}),  # confident enough: α+β = 4
        state({"finance": 2.0}),  # p 0.88: we're fairly sure
    ],
)
def test_no_prompt_when_confident_or_sure(reader):
    got = annotate(doc([demand("b", "c_bond", salience=0.8)]), reader)
    assert got.prompt is None


def test_no_prompt_below_salience():
    assert annotate(doc([demand("b", "c_bond", salience=0.6)])).prompt is None


def test_three_prompts_a_day_but_a_prompted_article_keeps_its_prompt():
    article = doc([demand("b", "c_bond", salience=0.8)])
    full = ScoringInputs(prompted_today=("a1", "a2", "a3"))
    assert annotate(article, inputs=full).prompt is None
    reload = ScoringInputs(prompted_today=("a1", "x", "a3"))
    assert annotate(article, inputs=reload).prompt is not None


# ---------------------------------------------------------------- pre-read path


CHAIN = ConceptGraph(
    ConceptGraphFile(
        version="chain",
        concepts=[
            concept("c_a", "finance", 0.0),
            concept("c_b", "finance", 0.0, prereqs=["c_a"]),
            concept("c_c", "finance", 0.0, prereqs=["c_b"]),
            concept("c_d", "finance", 0.0, prereqs=["c_c"]),
            concept("c_e", "finance", 0.0, prereqs=["c_d"]),
        ],
    )
)


def test_preread_walks_weak_prerequisites_at_most_three_steps():
    reader = state(edges={"c_a": edge(0.1), "c_b": edge(0.2), "c_c": edge(0.3), "c_d": edge(0.1)})
    article = doc([demand("e", "c_e", salience=1.0)])
    inputs = ScoringInputs(
        explainers={"c_c": ExplainerRef("other", "On C", 300), "c_d": ExplainerRef("x", "Me", 9)}
    )
    got = sc.annotate(article, CHAIN, reader, "balanced", NOW, inputs).preread
    assert got is not None and got.concept_id == "c_e"
    assert [s.concept_id for s in got.steps] == ["c_c", "c_d", "c_e"]  # most basic first
    assert got.steps[0].article == ExplainerRef("other", "On C", 300)
    assert got.steps[1].article is None  # the article being read doesn't count
    assert not any(s.known for s in got.steps)  # stopped at the step limit: no ticked step


def test_preread_stops_at_a_known_prerequisite_and_shows_it_ticked():
    reader = state(edges={"c_d": edge(0.75), "c_e": edge(0.1)})
    article = doc([demand("e", "c_e", salience=1.0)])
    got = sc.annotate(article, CHAIN, reader, "balanced", NOW).preread
    assert got is not None and [s.concept_id for s in got.steps] == ["c_d", "c_e"]
    assert [s.known for s in got.steps] == [True, False]  # where the path starts from


def test_preread_ticked_step_tie_break_is_highest_p_then_id():
    graph = ConceptGraph(ConceptGraphFile(version="tie", concepts=[
        concept("c_x", "finance", 0.0), concept("c_y", "finance", 0.0),
        concept("c_z", "finance", 0.0),
        concept("c_goal", "finance", 0.0, prereqs=["c_z", "c_y", "c_x"]),
    ]))  # fmt: skip
    reader = state(edges={"c_x": edge(0.8), "c_y": edge(0.9), "c_z": edge(0.9),
                          "c_goal": edge(0.1)})  # fmt: skip
    got = sc.annotate(doc([demand("g", "c_goal", salience=1.0)]), graph, reader, "balanced",
                      NOW).preread  # fmt: skip
    assert got is not None and got.steps[0].concept_id == "c_y" and got.steps[0].known


def test_spans_carry_the_concept_band_and_a_highlight_level():
    reader = state(edges={"c_e": edge(0.1)})
    span = sc.annotate(doc([demand("e", "c_e", salience=1.0)]), CHAIN, reader, "guided",
                       NOW).spans[0]  # fmt: skip
    assert (span.band, span.level) == ("unaware", "new")
    refresher = sc.SpanAnnotation(**{**span.__dict__, "band": "understands"})
    assert refresher.level == "refresher"


def test_preread_needs_the_assumed_mean_above_threshold():
    reader = state(edges={"c_e": edge(0.1)})
    explained = doc([demand("e", "c_e", explained=True)])  # not assumed
    assert sc.annotate(explained, CHAIN, reader, "balanced", NOW).preread is None
    article = doc([demand("e", "c_e", salience=0.3)])  # 0.9·0.3 = 0.27 < 0.45
    assert sc.annotate(article, CHAIN, reader, "balanced", NOW).preread is None


@pytest.mark.parametrize("source", ["user_ingested", "extension"])
def test_explainer_index_prefers_shortest_and_skips_reader_brought(source):
    long = doc([demand("x", "c_bond", explained=True)], words=900, content_id="long")
    short = doc([demand("x", "c_bond", explained=True)], words=200, content_id="short")
    opened = doc([demand("x", "c_bond", explained=True)], words=50, content_id="opened")
    opened = opened.model_copy(update={"source": source})
    got = sc.explainer_index([long, opened, short])
    assert got["c_bond"].content_id == "short"


# ---------------------------------------------------------------- personas


PERSONA_GRAPH = ConceptGraph(
    ConceptGraphFile(
        version="personas",
        concepts=[
            concept("c_bond_yields", "finance", 0.0),
            concept("c_yield_curve", "finance", 0.0, prereqs=["c_bond_yields"]),
            concept("c_derivative_contracts", "finance", 0.1),
            concept("c_fiscal_consolidation", "policy", 0.1),
            concept("c_phillips_curve", "economics", 0.1),
            concept("c_quantitative_easing", "economics", 0.2),
            concept("c_ipo", "business", -0.6),
        ],
    )
)


def persona_state(key):
    t = build_template(key, PERSONAS[key], PERSONA_GRAPH, NOW)
    return ReaderState(theta=t.theta, edges=t.edges)


def test_personas_see_different_not_nested_sets():
    ids = [c.id for c in PERSONA_GRAPH.concepts if c.id != "c_bond_yields"]
    demands = [demand(cid, cid, pid=f"p{i}", start=i * 100, salience=0.9)
               for i, cid in enumerate(ids)]  # fmt: skip
    article = doc(demands, paras(len(ids), 100))
    sets = {
        k: set(span_ids(sc.annotate(article, PERSONA_GRAPH, persona_state(k), "balanced", NOW)))
        for k in PERSONAS
    }
    trader, policy, newcomer = sets["trader"], sets["policy_student"], sets["newcomer"]
    assert trader - policy and policy - trader
    assert "c_derivative_contracts" in policy and "c_derivative_contracts" not in trader
    assert "c_fiscal_consolidation" in trader and "c_fiscal_consolidation" not in policy
    assert len(newcomer) > max(len(trader), len(policy))  # the newcomer needs the most help
    assert "c_ipo" in policy and "c_ipo" not in newcomer  # but an engineer knows what an IPO is


def test_no_prompt_while_learning_is_paused():
    article = doc([demand("b", "c_bond", salience=0.8)])
    assert annotate(article, inputs=ScoringInputs(prompts_allowed=False)).prompt is None


def test_span_level_uses_the_uncapped_concept_band_not_the_capped_span_p():
    # c_e is understood (0.6) but its prerequisite c_d is weak, so the span's p is capped and
    # it is shown; the highlight and card still say "refresher" (the band explain uses).
    reader = state(edges={"c_e": edge(0.6), "c_d": edge(0.05)})
    spans = sc.annotate(doc([demand("e", "c_e", salience=1.0)]), CHAIN, reader, "guided", NOW).spans
    assert spans and spans[0].p_know < 0.5
    assert (spans[0].band, spans[0].level) == ("understands", "refresher")
