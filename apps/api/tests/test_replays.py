"""M9 part 2 replay reports: pure, so the tables can be trusted."""

from scripts.replay_merges import Row, report
from tests.test_growth import Script, concept  # at collection: it imports LiteLLM


def test_merge_report_counts_false_merges_and_misses():
    rows = [
        Row("Forever chemicals", "PFAS", 0.899, "same", True),
        Row("PFAS", "PFOS", 0.971, "different", True),  # a false merge above the duplicate
        Row("Edge", "Node", 0.94, "different", False),
        Row("A", "B", 0.86, "same", False),  # a missed duplicate
    ]
    out = report(rows, 0.0123)
    assert "**4 pairs: false merges 1 (1 at cosine ≥ 0.899), missed duplicates 1.**" in out
    assert out.count("**disagree**") == 2 and "$0.0123" in out


def test_a_concept_is_never_its_own_prerequisite_candidate():
    from types import SimpleNamespace

    from scripts.replay_prereqs import pool_without

    pool = [SimpleNamespace(id="c_pfos"), SimpleNamespace(id="c_chemistry")]
    assert [c.id for c in pool_without(pool, "c_pfos")] == ["c_chemistry"]


def test_the_cut_drops_every_wrong_edge_and_keeps_90_percent_of_the_right():
    from scripts.replay_prereqs import Edge, choose

    right = [Edge(f"c{i}", "p", 0.6 + i / 100, True) for i in range(10)]
    wrong = [Edge("PFOS", "PHOSITA", 0.55, False)]
    t, n = choose(right + wrong)
    assert t == 0.6 and n["dropped_wrong"] == 1 and n["dropped_right"] == 0


def test_when_no_cut_does_both_it_keeps_90_percent_of_the_right():
    from scripts.replay_prereqs import Edge, choose

    right = [Edge(f"c{i}", "p", 0.5 + i / 100, True) for i in range(10)]
    wrong = [Edge("x", "y", 0.95, False)]  # more confident than every right edge
    t, n = choose(right + wrong)
    assert n["kept_wrong"] == 1 and n["dropped_right"] <= 1


def test_the_grown_sample_is_fixed_by_its_ids_and_seed():
    from scripts.sample_grown import sample

    ids = [f"c_{i}" for i in range(78)]
    first = sample(ids, 1015)
    assert len(first) == 30 and len(set(first)) == 30
    assert sample(list(reversed(ids)), 1015) == first  # order of the input doesn't matter
    assert sample(ids, 1016) != first


def _grown_doc(cid, label, added_at, source="src1", domain="sports"):
    doc = concept(cid, label, domain=domain, vec=(0.6, 0.8)).model_dump()
    return doc | {"added_at": added_at, "source_cid": source, "prompt_versions": {}}


async def test_the_merge_replay_writes_only_its_report(docs, monkeypatch, tmp_path):
    import json

    from app import llm
    from scripts import replay_merges

    (tmp_path / "merge_verdicts.json").write_text(json.dumps({"pairs": [
        {"a": "PFAS", "b": "Forever chemicals", "cosine": 0.899, "verdict": "same"},
        {"a": "PFAS", "b": "PFOS", "cosine": 0.971, "verdict": "different"},
    ]}))  # fmt: skip
    monkeypatch.setattr(replay_merges, "EVALS", tmp_path)
    monkeypatch.setattr(llm, "run_with_meta", Script({"link_merge": lambda v: {"decisions": [
        {"pair": 0, "same": True}, {"pair": 1, "same": False}]}}))  # fmt: skip
    assert await replay_merges.main() == 0
    assert "false merges 0" in (tmp_path / "merge_replay.md").read_text()
    assert docs.written == set()  # no store write (the spend ledger is the fake's)


async def test_the_prereq_replay_proposes_without_writing_to_the_store(docs, monkeypatch, tmp_path):
    import json
    from datetime import UTC, datetime

    from app import llm
    from app.graph.graph import ConceptGraph
    from app.graph.loader import get_graph, set_graph
    from app.graph.models import ConceptGraphFile
    from scripts import replay_prereqs

    early = datetime(2026, 10, 12, tzinfo=UTC)
    docs.docs["graph_growth/c_pfos"] = _grown_doc("c_pfos", "PFOS", early, domain="environment")
    previous = get_graph()
    graph = ConceptGraph(ConceptGraphFile(version="t", concepts=[
        concept("c_pfos", "PFOS", domain="environment", vec=(0.6, 0.8)),
        concept("c_chemistry", "Chemistry", domain="science", vec=(0.62, 0.78)),
    ]))  # fmt: skip

    async def served(uri):
        set_graph(graph)
        return 0

    seen: list[str] = []

    def prereqs(v):
        seen.append(v["concepts"])
        return {
            "concepts": [
                {"concept": 0, "prerequisites": [{"id": "c_chemistry", "confidence": 0.8}]}
            ]
        }

    monkeypatch.setattr("app.graph.loader.load_serving_graph", served)
    monkeypatch.setattr(replay_prereqs, "LOCAL", tmp_path)
    monkeypatch.setattr(llm, "run_with_meta", Script({"concept_prereqs": prereqs}))
    written = set(docs.written)
    try:
        assert await replay_prereqs.propose() == 0
    finally:
        set_graph(previous)
    assert "c_pfos" not in seen[0]  # never its own candidate
    blind = json.loads((tmp_path / "prereq_blind.json").read_text())
    want = {
        "concept_id": "c_pfos", "concept": "PFOS", "domain": "environment",
        "prereq_id": "c_chemistry", "prereq": "Chemistry", "prereq_domain": "science",
    }  # fmt: skip
    assert blind == [want]
    assert "confidence" not in json.dumps(blind) and docs.written == written


async def test_the_sample_takes_only_concepts_up_to_the_cutoff(docs, monkeypatch, tmp_path):
    import argparse
    import json
    from datetime import UTC, datetime

    from app.store.content_repo import InMemoryContentStore, set_content_store
    from scripts import sample_grown

    early, late = datetime(2026, 10, 12, tzinfo=UTC), datetime(2026, 10, 15, tzinfo=UTC)
    for i in range(40):
        docs.docs[f"graph_growth/c_{i}"] = _grown_doc(
            f"c_{i}", f"Concept {i}", early if i < 35 else late
        )
    set_content_store(InMemoryContentStore())
    monkeypatch.setattr(sample_grown, "EVALS", tmp_path)
    try:
        args = argparse.Namespace(cutoff="2026-10-14T09:24:55.3Z", seed=1015)
        assert await sample_grown.main(args) == 0
        first = json.loads((tmp_path / "grown_sample.json").read_text())
        assert await sample_grown.main(args) == 0
        again = json.loads((tmp_path / "grown_sample.json").read_text())
    finally:
        set_content_store(None)
    assert len(first["population"]) == 35 and "c_39" not in first["population"]
    assert [x["id"] for x in first["sample"]] == [x["id"] for x in again["sample"]]
    assert len(first["sample"]) == 30
