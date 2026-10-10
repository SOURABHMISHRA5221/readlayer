"""Online concept growth (M2.2 plan §C.2): picking, verification, merge, store, prerequisites."""

import pytest
from pydantic import ValidationError

from app import llm
from app.graph import growth
from app.graph.enrich import ConceptInfo
from app.graph.graph import ConceptGraph
from app.graph.grow import grow
from app.graph.models import Concept, ConceptGraphFile
from app.graph.overrides import Overrides
from app.ingest.models import Anchor, Demand
from app.store.docstore import InMemoryDocStore
from app.store.growth_repo import GrowthRepo
from scripts.build_concepts import OVERRIDES_FILE
from tests.fakes import meta


def concept(cid, label, domain="sports", b=0.0, kind="idea", vec=(1.0, 0.0)):
    return Concept(id=cid, label=label, domain=domain, definition=f"{label} defined here.",
                   base_difficulty=b, kind=kind, embedding=list(vec))  # fmt: skip


GRAPH = ConceptGraph(ConceptGraphFile(version="g1", concepts=[
    concept("c_football", "Association football", b=-1.0, vec=(1.0, 0.0)),
    concept("c_goal", "Goal", b=-1.5, vec=(0.9, 0.1)),
    concept("c_fifa", "FIFA", kind="institution", vec=(0.0, 1.0)),
]))  # fmt: skip
TEXT = "The striker was ruled offside before the false nine dropped deep to receive."


def demand(did, label, salience=0.8, target=None, kind="concept"):
    anchor = Anchor(exact=label.split()[0], prefix="", suffix="", start=0, end=3)
    return Demand(id=did, paragraph_id="p0", type=kind, label=label, target_id=target,
                  salience=salience, explained_in_text=False, zipf=3.0, anchor=anchor)  # fmt: skip


class Script:
    def __init__(self, replies):
        self.replies, self.calls = replies, []

    async def __call__(self, task, schema, prompt_vars):
        self.calls.append(task)
        return llm.LLMResult(
            schema.model_validate(self.replies[task](prompt_vars)), meta(task=task)
        )


def info(domain="sports", kind="method", spec=3):
    return {"id": 0, "definition": "A tactical role in football, defined here.",
            "specialization": spec, "domain": domain, "kind": kind}  # fmt: skip


async def embed_far(texts):
    return [[0.6, 0.8] for _ in texts]  # cosine < 0.88 to every graph concept


def test_pick_takes_unlinked_concepts_once_per_label_most_salient_first():
    ds = [demand("d1", "False nine", 0.6), demand("d2", "false nine", 0.9),
          demand("d3", "Goal", 0.95, target="c_goal"), demand("d4", "Offside", 0.7),
          demand("d5", "Pep", 0.99, kind="context")]  # fmt: skip
    got = growth.pick(ds, {"p0": TEXT}, limit=5)
    assert [p.label for p in got] == ["false nine", "Offside"]
    assert set(got[0].demand_ids) == {"d1", "d2"}
    assert len(growth.pick(ds, {"p0": TEXT}, limit=1)) == 1


def test_verified_needs_a_kept_kind_and_specialization_two():
    assert growth.verified(ConceptInfo(**info()))
    assert not growth.verified(ConceptInfo(**info(spec=1)))
    assert not growth.verified(ConceptInfo(**info(kind="company")))
    with pytest.raises(ValidationError):  # a domain outside the taxonomy never validates
        ConceptInfo(**info(domain="astrology"))


def test_never_merge_kinds_match_the_overrides_file():
    assert set(Overrides.load(OVERRIDES_FILE).never_merge_kind) == growth.NEVER_MERGE_KINDS


async def test_a_new_concept_is_verified_stored_and_linked_with_existing_prerequisites():
    repo = GrowthRepo(InMemoryDocStore())
    runner = Script({
        "concept_define": lambda v: {"concepts": [info()]},
        "concept_prereqs": lambda v: {"concepts": [{"concept": 0, "prerequisites": [
            {"id": "c_football", "confidence": 0.9}, {"id": "c_made_up", "confidence": 0.9}]}]},
    })  # fmt: skip
    ds = [demand("d1", "False nine"), demand("d2", "false nine", 0.5)]
    out = await grow(GRAPH, ds, {"p0": TEXT}, 5, "cid1", repo, runner, embed_far)
    (c,) = out.added
    assert c.id == "c_false_nine" and c.kind == "method" and c.domain == "sports"
    assert c.prerequisites == ["c_football"]  # the invented id is dropped
    assert out.links == {"d1": "c_false_nine", "d2": "c_false_nine"} and out.grown == {"d1", "d2"}
    assert (await repo.get("c_false_nine")).source_cid == "cid1"
    assert runner.calls == ["concept_define", "concept_prereqs"]  # one batched call each


async def test_an_unverified_answer_grows_nothing():
    repo = GrowthRepo(InMemoryDocStore())
    runner = Script({"concept_define": lambda v: {"concepts": [info(kind="person")]}})
    out = await grow(GRAPH, [demand("d1", "Pep Guardiola")], {"p0": TEXT}, 5, "c", repo, runner,
                     embed_far)  # fmt: skip
    assert out.added == [] and out.links == {} and out.rejected == 1


async def test_a_near_existing_concept_is_linked_by_merge_not_grown():
    async def embed_near(texts):
        return [[1.0, 0.0] for _ in texts]  # same as "Association football"

    runner = Script({"link_merge": lambda v: {"decisions": [{"pair": 0, "same": True}]}})
    out = await grow(GRAPH, [demand("d1", "Soccer")], {"p0": TEXT}, 5, "c",
                     GrowthRepo(InMemoryDocStore()), runner, embed_near)  # fmt: skip
    assert out.links == {"d1": "c_football"} and out.grown == set() and out.merged == 1


async def test_named_organisations_never_absorb_another_label():
    async def embed_fifa(texts):
        return [[0.0, 1.0] for _ in texts]

    runner = Script({"concept_define": lambda v: {"concepts": [info(kind="institution", spec=2)]},
                     "concept_prereqs": lambda v: {"concepts": []}})  # fmt: skip
    out = await grow(GRAPH, [demand("d1", "UEFA")], {"p0": TEXT}, 5, "c",
                     GrowthRepo(InMemoryDocStore()), runner, embed_fifa)  # fmt: skip
    assert "link_merge" not in runner.calls  # FIFA is never offered as a merge for UEFA
    assert [c.label for c in out.added] == ["UEFA"]


async def test_an_id_stored_first_by_another_instance_is_reused_only_for_the_same_label():
    store = InMemoryDocStore()
    repo = GrowthRepo(store)
    await repo.create_if_absent(concept("c_false_nine", "False nine"), "other", {})
    runner = Script({"concept_define": lambda v: {"concepts": [info()]},
                     "concept_prereqs": lambda v: {"concepts": []}})  # fmt: skip
    out = await grow(GRAPH, [demand("d1", "False nine")], {"p0": TEXT}, 5, "c", repo, runner,
                     embed_far)  # fmt: skip
    assert out.links == {"d1": "c_false_nine"}
    assert (await repo.get("c_false_nine")).source_cid == "other"  # never overwritten


async def test_no_slots_no_calls():
    runner = Script({})
    out = await grow(GRAPH, [demand("d1", "False nine")], {"p0": TEXT}, 0, "c",
                     GrowthRepo(InMemoryDocStore()), runner, embed_far)  # fmt: skip
    assert out.added == [] and runner.calls == []
