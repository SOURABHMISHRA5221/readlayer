"""Eval case files stay well-formed (offline; the suite itself needs real models)."""

from collections import Counter

from app.explain import checks
from app.explain.models import Explanation
from evals.run import inputs_for, load

KINDS = {"dropped_hedge", "dropped_attribution", "changed_number", "flipped_negation",
         "opinion_as_fact"}  # fmt: skip


def test_case_counts_and_kinds():
    adversarial, good, injection = (
        load("faithfulness_adversarial"), load("faithfulness_good"), load("injection")
    )  # fmt: skip
    assert len(adversarial) == 15 and len(good) == 25 and len(injection) == 10
    assert Counter(c["perturbation"] for c in adversarial) == dict.fromkeys(KINDS, 3)
    assert Counter(c["mode"] for c in good) == {"span": 20, "paragraph": 5}
    ids = [c["id"] for c in adversarial + good + injection]
    assert len(ids) == len(set(ids))


def test_each_adversarial_card_changes_only_the_restatement_of_its_base():
    good = {c["id"]: c for c in load("faithfulness_good")}
    for case in load("faithfulness_adversarial"):
        base = good[case["base"]]
        assert case["paragraph"] == base["paragraph"] and case["span"] == base["span"]
        assert case["card"]["background"] == base["card"]["background"]
        assert case["card"]["author_says"] != base["card"]["author_says"]


def test_cases_build_inputs_and_cards():
    for case in load("faithfulness_good") + load("faithfulness_adversarial"):
        inputs = inputs_for(case)
        Explanation(**case["card"])
        assert inputs.sentence in inputs.paragraph or inputs.mode == "paragraph"
        checks.check(inputs, case["card"]["author_says"])  # runs without error
    for case in load("injection"):
        assert case["canaries"] and inputs_for(case).span in case["paragraph"]


def test_background_cases_are_well_formed():
    cases = load("background")
    assert [c["id"] for c in cases] == ["B01", "B02", "B03", "B04", "B05"]
    assert {c["expect"] for c in cases} == {"reject", "accept"}
    assert {c["issue"] for c in cases if c["expect"] == "reject"} == {
        "article_claim", "contradicts", "link",
    }  # fmt: skip
    for c in cases:
        inputs = inputs_for(c)
        assert inputs.paragraph and c["background"]
