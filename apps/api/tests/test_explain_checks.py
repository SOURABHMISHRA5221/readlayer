"""Deterministic verifier checks and explanation inputs (DESIGN §7). Pure, no LLM."""

from datetime import UTC, datetime

import pytest

from app.explain import checks
from app.explain.inputs import (
    PROMPT_VAR_KEYS,
    ExplainInputs,
    locate,
    paragraph_inputs,
    sentence_at,
    span_inputs,
    split_sentences,
)
from app.ingest.models import StoredParagraph
from tests.test_scorer import GRAPH, demand, doc, edge, state

NOW = datetime.now(UTC)
PARA = (
    "The yield curve inverted last week. Analysts said the Fed may cut rates by 25 basis "
    "points, but the bank has not signalled a move. Inflation was 3.2 per cent in March."
)


def inputs(mode="span", sentence=None, paragraph=PARA) -> ExplainInputs:
    return ExplainInputs(
        mode=mode,
        content_id="x",
        paragraph_id="p0",
        span="Fed",
        sentence=sentence or paragraph,
        paragraph=paragraph,
        concepts=(),
        band="heard of",
        thinks_in="software",
        style="normal",
    )


SENT = (
    "Analysts said the Fed may cut rates by 25 basis points, but the bank has not signalled a move."
)


def test_faithful_restatement_passes():
    ok = "Analysts said the Fed may cut rates by 25 basis points, though it has not signalled it."
    assert checks.check(inputs(sentence=SENT), ok) == []


@pytest.mark.parametrize(
    ("restatement", "code"),
    [
        ("Analysts said the Fed will cut rates by 25 bps but has not signalled it.", "hedge"),
        ("The Fed may cut rates by 25 bps, though it has not signalled a move.", "attribution"),
        ("Analysts said the Fed may cut rates by 50 bps but has not signalled it.", "number"),
        ("Analysts said the Fed may cut rates by 25 bps and has signalled a move.", "negation"),
    ],
)
def test_each_rule_catches_its_perturbation(restatement, code):
    reasons = checks.check(inputs(sentence=SENT), restatement)
    assert [r for r in reasons if r.startswith(code)], reasons


def test_number_normalisation():
    para = "Profit rose 40 per cent to Rs 3,200 crore; the deal was worth $3.5bn."
    i = inputs(paragraph=para, sentence=para)
    assert (
        checks.check(i, "Profit rose 40% to Rs 3,200 crore; the deal was worth $3.5 billion.") == []
    )
    assert checks.check(i, "Profit rose 45% to Rs 3,200 crore.")[0].startswith("number")


def test_number_words_in_the_source_match_digits_and_pronoun_one_is_ignored():
    para = "Three banks raised rates."
    i = inputs(paragraph=para, sentence=para)
    assert checks.check(i, "3 banks raised rates, one of them sharply.") == []


def test_span_mode_scopes_hedges_to_the_spans_sentence():
    # The paragraph is hedged elsewhere; the span's own sentence is a plain fact.
    i = inputs(sentence="The yield curve inverted last week.")
    assert checks.check(i, "The yield curve inverted last week.") == []


def test_paragraph_mode_checks_the_whole_paragraph():
    i = inputs(mode="paragraph")
    reasons = checks.check(i, "The yield curve inverted last week. Inflation was 3.2% in March.")
    assert {r.split(":")[0] for r in reasons} >= {"hedge_dropped", "attribution_dropped"}


def test_links_not_in_the_source_are_rejected_in_either_part():
    i = inputs(sentence=SENT)
    ok = "Analysts said the Fed may cut by 25 bps; it has not signalled a move."
    assert checks.check(i, ok, background="See evil.example.com for more.")[0].startswith(
        "link_in_background"
    )


def test_sentences_and_anchor_location():
    text = "First one. Second has the Fed. Third."
    assert [s for _, s in split_sentences(text)] == ["First one.", "Second has the Fed.", "Third."]
    at = locate(text, "Fed", "has the ")
    assert sentence_at(text, at) == "Second has the Fed."
    assert locate(text, "ECB", "") == -1


def test_span_inputs_use_the_readers_band_and_only_allowed_vars():
    para = StoredParagraph(id="p0", text="The yield_curve flattened. Bonds fell.", structure=0.0)
    d = demand("d1", "c_yield_curve")
    article = doc([d], [para])
    novice = span_inputs(article, d, GRAPH, state(), NOW, "cricket", "short")
    assert novice is not None
    assert novice.band == "heard of"  # prior σ(0 − 1) = 0.27
    expert = span_inputs(
        article, d, GRAPH, state(edges={"c_yield_curve": edge(0.9, 10)}), NOW, None, "short"
    )
    assert expert is not None and expert.band == "can explain"
    assert novice.sentence == "The yield_curve flattened."
    assert "Bond" in novice.prompt_vars()["concepts"]  # prerequisite definitions included
    assert set(novice.prompt_vars()) == PROMPT_VAR_KEYS
    assert novice.cache_key("v1") != expert.cache_key("v1")
    assert novice.cache_key("v1") != novice.cache_key("v2")


def test_unlinked_demand_has_no_inputs():
    d = demand("d1", None)
    assert span_inputs(doc([d]), d, GRAPH, state(), NOW, None, "normal") is None


def test_paragraph_inputs_pick_top_concepts_and_domain_band():
    para = StoredParagraph(id="p0", text="Inflation and the yield curve.", structure=0.0)
    ds = [demand("d1", "c_inflation", salience=0.4), demand("d2", "c_yield_curve", salience=0.9)]
    i = paragraph_inputs(
        doc(ds, [para]), "p0", GRAPH, state(theta={"finance": 2.0}), None, "normal"
    )
    assert i is not None and i.mode == "paragraph"
    assert [c.concept_id for c in i.concepts] == ["c_yield_curve", "c_inflation"]
    assert i.band == "can explain"  # finance carries more salience: σ(2.0) = 0.88
