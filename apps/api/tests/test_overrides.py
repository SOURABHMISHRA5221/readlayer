import pytest

from app import llm
from app.graph.models import Concept, ConceptGraphFile
from app.graph.overrides import (
    Overrides,
    filter_pairs,
    patch_adds,
    patch_remove_aliases,
    patch_renames,
    patch_split_sources,
    pending_adds,
    split_groups,
)
from scripts import build_concepts
from scripts.apply_overrides import unique_id
from scripts.build_concepts import OVERRIDES_FILE, Candidate, dedupe
from tests.fakes import meta

OVERRIDES = Overrides.model_validate(
    {
        "never_merge": [["Notional amount", "Denomination"]],
        "split": [
            {"label": "Notional amount", "from": "Denomination", "aliases": ["notional value"]}
        ],
        "rename": [{"from": "Bimallic coin", "to": "Bimetallic coin"}],
    }
)


def test_committed_overrides_file_is_valid_and_has_the_m21_fixes():
    ov = Overrides.load(OVERRIDES_FILE)
    assert ov.renamed("Bimallic coin") == "Bimetallic coin"
    assert any(s.label == "Notional amount" and s.from_ == "Denomination" for s in ov.split)


def test_missing_file_means_no_overrides(tmp_path):
    assert Overrides.load(tmp_path / "none.yaml") == Overrides()


def test_unknown_keys_are_rejected():
    with pytest.raises(ValueError):
        Overrides.model_validate({"spilt": []})


def test_never_merge_and_split_pairs_are_blocked():
    keys = ["notional amount", "denomination", "face value", "notional value"]
    pairs = [(0, 1), (1, 2), (1, 3)]
    assert filter_pairs(pairs, keys, OVERRIDES) == [(1, 2)]


def test_split_pulls_members_out_even_through_a_third_label():
    keys = ["notional amount", "denomination", "face value", "notional value"]
    groups = [[0, 1, 2, 3]]  # merged transitively via face value
    assert sorted(map(sorted, split_groups(groups, keys, OVERRIDES))) == [[0, 3], [1, 2]]


class GreedyCache:
    """Embeds every label to the same vector and accepts every merge: worst case for splits."""

    async def embed(self, texts, task_type):
        return [[1.0, 0.0] for _ in texts]

    async def run(self, task, schema, prompt_vars):
        n = prompt_vars["pair_count"]
        reply = {"decisions": [{"pair": i, "same": True} for i in range(n)]}
        return llm.LLMResult(schema.model_validate(reply), meta())


def cand(label: str, group: int) -> Candidate:
    c = Candidate(build_concepts.build.normalize_label(label))
    c.labels[label] += 1
    c.news_labels[label] += 1
    c.news_exacts[label.lower()] += 1
    c.groups.add(group)
    return c


async def test_overrides_survive_a_rebuild():
    cands = [
        cand("Denomination", 0),
        cand("Face value", 1),
        cand("Notional amount", 2),
        cand("Notional value", 3),
    ]
    dd = await dedupe(cands, GreedyCache(), 0.88, [], OVERRIDES)
    by_label = {m.label: m for m in dd.merged}
    assert set(by_label) == {"Denomination", "Notional amount"}
    assert by_label["Notional amount"].forced
    assert {c.key for c in by_label["Notional amount"].members} == {
        "notional amount",
        "notional value",
    }
    assert not by_label["Denomination"].forced


async def test_rename_survives_a_rebuild_and_hides_the_typo():
    dd = await dedupe([cand("Bimallic coin", 0)], GreedyCache(), 0.88, [], OVERRIDES)
    (merged,) = dd.merged
    assert merged.label == "Bimetallic coin"
    assert "Bimallic coin" not in merged.aliases()


def concept(cid: str, label: str, aliases=(), prereqs=()) -> Concept:
    return Concept(
        id=cid,
        label=label,
        aliases=list(aliases),
        domain="finance",
        definition="d" * 12,
        base_difficulty=0.0,
        prerequisites=list(prereqs),
        embedding=[1.0, 0.0],
    )


def graph_file() -> ConceptGraphFile:
    return ConceptGraphFile(
        version="t",
        concepts=[
            concept("c_denomination", "Denomination", ["Notional amount", "Face value"]),
            concept("c_bimallic_coin", "Bimallic coin", ["bi-metallic"]),
            concept("c_coin_design", "Coin design", prereqs=["c_bimallic_coin"]),
        ],
    )


def test_patch_renames_moves_id_and_references():
    file, moved = patch_renames(graph_file(), OVERRIDES, unique_id)
    assert moved == {"c_bimallic_coin": "c_bimetallic_coin"}
    by_id = {c.id: c for c in file.concepts}
    assert by_id["c_bimetallic_coin"].label == "Bimetallic coin"
    assert by_id["c_coin_design"].prerequisites == ["c_bimetallic_coin"]


def test_patch_split_strips_aliases_and_is_idempotent():
    file, todo = patch_split_sources(graph_file(), OVERRIDES)
    denom = next(c for c in file.concepts if c.id == "c_denomination")
    assert denom.aliases == ["Face value"]
    assert [(s.label, src) for s, src in todo] == [("Notional amount", "c_denomination")]
    with_new = file.model_copy(
        update={"concepts": [*file.concepts, concept("c_notional_amount", "Notional amount")]}
    )
    again, todo_again = patch_split_sources(with_new, OVERRIDES)
    assert todo_again == [] and again == with_new
    _, moved_again = patch_renames(
        patch_renames(graph_file(), OVERRIDES, unique_id)[0], OVERRIDES, unique_id
    )
    assert moved_again == {}


def test_heldout_urls_may_not_overlap_the_corpus(tmp_path, monkeypatch):
    corpus = tmp_path / "corpus.txt"
    heldout = tmp_path / "heldout.txt"
    corpus.write_text("https://x.test/a\tmint\n")
    heldout.write_text("https://x.test/a\tmint\n")
    monkeypatch.setattr(build_concepts, "CORPUS_FILE", corpus)
    monkeypatch.setattr(build_concepts, "HELDOUT_FILE", heldout)
    with pytest.raises(SystemExit):
        build_concepts.corpus_sources()
    heldout.write_text("https://x.test/b\tmint\n")
    assert set(build_concepts.corpus_sources()) == {"https://x.test/a"}


@pytest.mark.parametrize("source", ["user_ingested", "extension"])
def test_reader_brought_docs_are_never_corpus(source):
    from tests.test_scorer import doc

    listed = doc([]).model_copy(update={"content_id": "a", "url": "https://x.test/a"})
    reader = listed.model_copy(
        update={"content_id": "b", "url": "https://x.test/b", "source": source}
    )
    unlisted = listed.model_copy(update={"content_id": "c", "url": "https://x.test/c"})
    sources = {"https://x.test/a": "mint", "https://x.test/b": "mint"}
    picked = build_concepts.select_corpus([listed, reader, unlisted], sources)
    assert [d.content_id for d in picked] == ["a"]


# ---------------------------------------------------------------- M2.2: remove_alias, add, kinds


def _c(cid, label, aliases=(), kind=None, domain="finance"):
    return Concept(
        id=cid,
        label=label,
        aliases=list(aliases),
        domain=domain,
        definition=f"Definition of {label}.",
        base_difficulty=0.0,
        kind=kind,
        embedding=[1.0, 0.0],
    )


M22_GRAPH = ConceptGraphFile(
    version="t",
    concepts=[
        _c("c_tax_levy", "Tax levy", ["levies", "Tax"], "tax", "policy"),
        _c(
            "c_s_p_dow_jones_indices",
            "S&P Dow Jones Indices",
            ["FTSE Russell", "Russell Indexes"],
            "index_provider",
        ),  # fmt: skip
        _c("c_fiscal_policy", "Fiscal policy", kind="policy", domain="policy"),
        _c("c_budget", "Budget", kind="idea", domain="policy"),
        _c("c_benchmark_index", "Benchmark index", kind="index"),
    ],
)


def _apply_m22(file, ov):
    file = patch_remove_aliases(file, ov)
    adds = pending_adds(file, ov)
    vectors = {a.label: [0.0, 1.0] for a in adds}
    return patch_adds(file, adds, vectors, lambda _s: 3.0, unique_id)


def test_committed_m22_overrides_fix_russell_tax_and_add_the_chancellor():
    ov = Overrides.load(OVERRIDES_FILE)
    file, added = _apply_m22(M22_GRAPH, ov)
    by_label = {c.label: c for c in file.concepts}
    assert by_label["S&P Dow Jones Indices"].aliases == []
    assert by_label["Tax levy"].aliases == ["levies"]
    chancellor = by_label["Chancellor of the Exchequer"]
    assert chancellor.kind == "role" and chancellor.jurisdiction == "GB"
    assert chancellor.aliases == []  # no bare "Chancellor": a German chancellor would match
    assert chancellor.prerequisites == ["c_fiscal_policy", "c_budget"]
    russell = by_label["FTSE Russell"]
    assert russell.kind == "index_provider" and russell.aliases == ["Russell Indexes"]
    assert {c.label for c in added} == {"Chancellor of the Exchequer", "FTSE Russell"}
    # "Russell Indexes" now resolves to FTSE Russell, not S&P Dow Jones Indices
    from app.graph.graph import ConceptGraph

    assert ConceptGraph(file).lookup("Russell Indexes").label == "FTSE Russell"
    # re-applying is a no-op
    again, more = _apply_m22(file, ov)
    assert more == [] and len(again.concepts) == len(file.concepts)


def test_add_rejects_a_dropped_kind_and_an_unknown_prerequisite():
    base = {"label": "X thing", "domain": "finance", "specialization": 2,
            "definition": "A definition long enough to pass."}  # fmt: skip
    with pytest.raises(ValueError, match="kept kind"):
        Overrides.model_validate({"add": [{**base, "kind": "company"}]})
    ov = Overrides.model_validate({"add": [{**base, "kind": "idea", "prerequisites": ["Nope"]}]})
    with pytest.raises(ValueError, match="unknown prerequisite"):
        _apply_m22(M22_GRAPH, ov)


def test_remove_alias_for_a_missing_concept_is_an_error():
    ov = Overrides.model_validate({"remove_alias": [{"label": "Gone", "aliases": ["x"]}]})
    with pytest.raises(ValueError, match="no concept"):
        patch_remove_aliases(M22_GRAPH, ov)


def test_named_organisations_never_absorb_a_differently_labelled_candidate():
    ov = Overrides.load(OVERRIDES_FILE)
    spdji = M22_GRAPH.concepts[1]
    assert ov.merge_refused(spdji, "Russell 2000 index family")
    assert not ov.merge_refused(spdji, "S&P Dow Jones Indices")  # identity is not a merge
    assert not ov.merge_refused(M22_GRAPH.concepts[3], "Union budget")  # kind idea: allowed
    assert not ov.merge_refused(_c("c_old", "Old", kind=None), "Older")  # pre-M2.2 concept
