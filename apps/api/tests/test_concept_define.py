import pytest

from app import llm
from app.graph.build import DROP_KINDS, KEEP_KINDS, apply_keep
from app.graph.enrich import (
    Entry,
    LinkQuestion,
    PrereqRequest,
    check_merges,
    confirm_links,
    define_concepts,
    propose_prereqs,
)
from tests.fakes import meta

KEEP_EXAMPLES = (
    "RBI",
    "SEBI",
    "MPC",
    "Federal Reserve",
    "Sensex",
    "Nifty",
    "GST",
    "RoDTEP",
    "PLI scheme",
    "hedge fund",
    "bank run",
    "crore",
    "brokerage firm",
    "subsidiary",
    "bond sell-off",
)


def test_prompt_states_the_keep_and_drop_contract():
    prompt = llm.load_prompt("concept_define")
    text = prompt.system
    assert prompt.version.startswith("concept_define-")
    for kind in KEEP_KINDS | DROP_KINDS:
        assert f'"{kind}"' in text, kind
    for example in KEEP_EXAMPLES:
        assert example in text, example
    assert 'never as "company" or "event"' in text
    assert 'never "company", "event" or "generic"' in text
    assert "{{concepts}}" in prompt.user and "<<<CONTENT>>>" in prompt.user


class ScriptedRunner:
    """Replies per call from a function of the rendered prompt vars."""

    def __init__(self, reply) -> None:
        self.reply = reply
        self.calls: list[dict] = []

    async def __call__(self, task, schema, prompt_vars):
        self.calls.append({"task": task, "vars": prompt_vars})
        return llm.LLMResult(schema.model_validate(self.reply(task, prompt_vars)), meta())


KINDS_BY_LABEL = {
    "RBI": "institution",
    "SEBI": "regulator",
    "MPC": "committee",
    "Sensex": "index",
    "GST": "tax",
    "RoDTEP": "scheme",
    "Inflation targeting": "policy",
    "Basis point": "jargon",
    "Repo rate": "idea",
    "Hedge fund": "entity_type",
    "Bank run": "market_event",
    "Crore": "unit",
    "Brokerage firm": "entity_type",
    "Subsidiary": "entity_type",
    "Bond sell-off": "market_event",
    "Tata Motors": "company",
    "Jerome Powell": "person",
    "Kerala": "place",
    "October MPC meeting": "event",
    "Growth": "generic",
}


async def test_institutions_kept_companies_and_people_dropped():
    labels = list(KINDS_BY_LABEL)

    def reply(task, prompt_vars):
        lines = [ln for ln in prompt_vars["concepts"].splitlines() if ln.startswith("[")]
        out = []
        for ln in lines:
            idx, label = ln[1:].split("] ", 1)
            out.append(
                {
                    "id": int(idx),
                    "definition": f"Definition of {label}.",
                    "specialization": 3,
                    "domain": "economics",
                    "kind": KINDS_BY_LABEL[label],
                }
            )
        return {"concepts": out}

    runner = ScriptedRunner(reply)
    ledger: list[llm.CallMeta] = []
    infos = await define_concepts([Entry(label) for label in labels], runner, ledger)
    kept = {labels[i] for i, info in infos.items() if apply_keep(info.kind)}
    assert kept == {
        "RBI",
        "SEBI",
        "MPC",
        "Sensex",
        "GST",
        "RoDTEP",
        "Inflation targeting",
        "Basis point",
        "Repo rate",
        "Hedge fund",
        "Bank run",
        "Crore",
        "Brokerage firm",
        "Subsidiary",
        "Bond sell-off",
    }
    assert len(ledger) == 1 and runner.calls[0]["task"] == "concept_define"


async def test_skipped_items_are_asked_again_once():
    asked: list[int] = []

    def reply(task, prompt_vars):
        n = prompt_vars["pair_count"]
        asked.append(n)
        # first sweep answers only pair 0 of each batch
        return {
            "decisions": [{"pair": 0, "same": True}]
            + ([{"pair": 99, "same": True}] if n > 1 else [])
        }

    pairs = [(Entry("a"), Entry("b")), (Entry("c"), Entry("d"))]
    decisions = await check_merges(pairs, ScriptedRunner(reply), [])
    assert asked == [2, 1]  # one batch, then one re-ask for the skipped pair
    assert decisions == {0: True, 1: True}


async def test_prereqs_only_from_own_candidates():
    def reply(task, prompt_vars):
        return {
            "concepts": [
                {
                    "concept": 0,
                    "prerequisites": [
                        {"id": "c_inflation", "confidence": 0.9},
                        {"id": "c_not_a_candidate", "confidence": 0.9},
                    ],
                }
            ]
        }

    req = PrereqRequest(Entry("Repo rate", definition="d"), (("c_inflation", "Inflation"),))
    out = await propose_prereqs([req], ScriptedRunner(reply), [])
    assert [p.id for p in out[0]] == ["c_inflation"]


async def test_confirm_links_rejects_ids_outside_candidates():
    def reply(task, prompt_vars):
        return {
            "answers": [
                {"mention": 0, "concept_id": "c_repo_rate"},
                {"mention": 1, "concept_id": "c_invented"},
                {"mention": 2, "concept_id": None},
            ]
        }

    cands = (("c_repo_rate", "Repo rate", "d", 0.9),)
    qs = [LinkQuestion(f"d{i}", "repo", "s", cands) for i in range(3)]
    runner = ScriptedRunner(reply)
    assert await confirm_links(qs, runner, []) == {0: "c_repo_rate", 1: None, 2: None}
    assert runner.calls[0]["task"] == "link_confirm"


@pytest.mark.parametrize(
    "task", ["link_merge", "concept_define", "concept_prereqs", "concept_wikidata", "link_confirm"]
)
def test_build_prompts_have_versions_and_routes(task):
    prompt = llm.load_prompt(task)
    assert prompt.version.startswith(f"{task}-v")
    assert task in llm.ROUTES and "<<<CONTENT>>>" in prompt.user
