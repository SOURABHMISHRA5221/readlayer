"""M9 part 2, P1 (R1, R2, R4): same-article duplicates merge in growth's one link_merge call."""

import re

from app.graph.grow import grow
from app.store.docstore import InMemoryDocStore
from app.store.growth_repo import GrowthRepo
from tests.test_growth import GRAPH, TEXT, Script, confirm_all, demand

# Unit vectors: the three chemicals sit close to each other (cosine ≥ 0.85) and far from GRAPH.
VECTORS = {
    "PFAS": (0.6, 0.8),
    "Forever chemicals": (0.66, 0.75),
    "PFOS": (0.55, 0.835),
    "Soccer": (1.0, 0.02),  # nearest c_football in GRAPH
    "Footy": (0.995, 0.05),
}


async def embed(texts):
    return [list(VECTORS[t]) for t in texts]


def merges(same: set[frozenset[str]]):
    """A link_merge reply: "same" for the label pairs in `same`, read from the rendered prompt."""

    def reply(prompt_vars):
        rows = re.findall(r'\[(\d+)\] "([^"]+)"[^|]*\|\s+"([^"]+)"', prompt_vars["pairs"])
        return {
            "decisions": [{"pair": int(i), "same": frozenset((a, b)) in same} for i, a, b in rows]
        }

    return reply


def define(prompt_vars):
    labels = re.findall(r"^\[(\d+)\] ", prompt_vars["concepts"], re.M)
    concept = {"definition": "A class of synthetic chemicals, defined here.", "specialization": 3,
               "domain": "environment", "kind": "method"}  # fmt: skip
    return {"concepts": [{"id": int(i), **concept} for i in labels]}


def runner(same):
    return Script({
        "link_merge": merges(same),
        "concept_define": define,
        "link_confirm": confirm_all,
        "concept_prereqs": lambda v: {"concepts": []},
    })  # fmt: skip


async def test_a_same_page_duplicate_becomes_one_concept_with_the_other_as_alias():
    ds = [
        demand("d1", "PFAS", 0.9),
        demand("d2", "Forever chemicals", 0.7),
        demand("d3", "PFOS", 0.6),
    ]
    r = runner({frozenset({"PFAS", "Forever chemicals"})})
    out = await grow(GRAPH, ds, {"p0": TEXT}, 5, "c", GrowthRepo(InMemoryDocStore()), r, embed)
    labels = sorted(c.label for c in out.added)
    assert labels == ["PFAS", "PFOS"]  # PFAS / PFOS asked and kept apart
    pfas = next(c for c in out.added if c.label == "PFAS")
    assert "Forever chemicals" in pfas.aliases
    assert out.links["d1"] == out.links["d2"] == pfas.id and out.links["d3"] != pfas.id
    assert r.calls.count("link_merge") == 1  # one call for every pair
    assert out.merged == 1


async def test_a_chain_of_same_answers_is_one_concept():
    ds = [
        demand("d1", "PFAS", 0.9),
        demand("d2", "Forever chemicals", 0.7),
        demand("d3", "PFOS", 0.6),
    ]
    r = runner({frozenset({"PFAS", "Forever chemicals"}), frozenset({"Forever chemicals", "PFOS"})})
    out = await grow(GRAPH, ds, {"p0": TEXT}, 5, "c", GrowthRepo(InMemoryDocStore()), r, embed)
    assert [c.label for c in out.added] == ["PFAS"]
    assert set(out.added[0].aliases) == {"Forever chemicals", "PFOS"}
    assert {out.links[d] for d in ("d1", "d2", "d3")} == {out.added[0].id}


async def test_a_group_with_a_member_in_the_graph_links_there_and_defines_nothing():
    ds = [demand("d1", "Soccer", 0.9), demand("d2", "Footy", 0.7)]
    r = runner({frozenset({"Soccer", "Association football"}), frozenset({"Soccer", "Footy"})})
    out = await grow(GRAPH, ds, {"p0": TEXT}, 5, "c", GrowthRepo(InMemoryDocStore()), r, embed)
    assert out.links == {"d1": "c_football", "d2": "c_football"} and out.added == []
    assert "concept_define" not in r.calls and out.merged == 2


async def test_different_answers_keep_every_pick():
    ds = [demand("d1", "PFAS", 0.9), demand("d2", "Forever chemicals", 0.7)]
    r = runner(set())
    out = await grow(GRAPH, ds, {"p0": TEXT}, 5, "c", GrowthRepo(InMemoryDocStore()), r, embed)
    assert sorted(c.label for c in out.added) == ["Forever chemicals", "PFAS"]
    assert all(not c.aliases for c in out.added) and out.merged == 0


async def test_a_batch_group_never_reaches_a_named_organisation():
    """UEFA and its long name merge with each other; FIFA (an institution) is never offered."""
    prompts: list[str] = []

    async def near_fifa(texts):
        return [[0.02, 1.0] if t == "UEFA" else [0.05, 0.998] for t in texts]

    base = merges({frozenset({"UEFA", "Union of European Football Associations"})})

    def spy(prompt_vars):
        prompts.append(prompt_vars["pairs"])
        return base(prompt_vars)

    r = Script({"link_merge": spy, "concept_define": define, "link_confirm": confirm_all,
                "concept_prereqs": lambda v: {"concepts": []}})  # fmt: skip
    ds = [demand("d1", "UEFA", 0.9), demand("d2", "Union of European Football Associations", 0.7)]
    out = await grow(GRAPH, ds, {"p0": TEXT}, 5, "c", GrowthRepo(InMemoryDocStore()), r, near_fifa)
    assert prompts and all("FIFA" not in p for p in prompts)
    assert [c.label for c in out.added] == ["UEFA"] and out.links["d2"] == out.added[0].id
