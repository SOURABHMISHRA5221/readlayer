import pytest

from app import llm
from app.graph.graph import ConceptGraph
from app.graph.linking import finish_links, link_demands, plan_links, sentence_around
from app.graph.loader import load_graph
from app.graph.models import Concept, ConceptGraphFile
from app.ingest.models import Anchor, Demand


def concept(cid, label, vec, aliases=(), prereqs=(), domain="economics"):
    return Concept(
        id=cid,
        label=label,
        aliases=list(aliases),
        domain=domain,
        definition="d",
        base_difficulty=0.0,
        prerequisites=list(prereqs),
        embedding=list(vec),
    )


def graph_file() -> ConceptGraphFile:
    return ConceptGraphFile(
        version="test",
        concepts=[
            concept("c_inflation", "Inflation", [1, 0, 0]),
            concept("c_interest_rate", "Interest rate", [0, 1, 0], prereqs=["c_inflation"]),
            concept(
                "c_repo_rate",
                "Repo rate",
                [0, 0.8, 0.6],
                aliases=["repo", "Repurchase rate"],
                prereqs=["c_interest_rate", "c_inflation"],
            ),
            concept(
                "c_rbi",
                "Reserve Bank of India",
                [0, 0, 1],
                aliases=["RBI", "repo"],
                domain="policy",
            ),
        ],
    )


@pytest.fixture
def graph() -> ConceptGraph:
    return ConceptGraph(graph_file())


def demand(did, label, exact=None, type_="concept", prefix=""):
    exact = exact or label
    return Demand(
        id=did,
        paragraph_id="p0",
        anchor=Anchor(exact=exact, prefix=prefix, suffix="", start=0, end=len(exact)),
        type=type_,
        label=label,
        salience=0.8,
        explained_in_text=False,
        zipf=3.0,
    )


def test_lookup_by_label_and_alias_with_ambiguous_alias_dropped(graph):
    assert graph.lookup("repo rates").id == "c_repo_rate"
    assert graph.lookup("Repurchase rate").id == "c_repo_rate"
    assert graph.lookup("rbi").id == "c_rbi"
    assert graph.lookup("repo") is None  # alias of two concepts
    assert graph.lookup("deflation") is None


def test_prerequisites_and_chain(graph):
    assert {c.id for c in graph.prerequisites("c_repo_rate")} == {"c_interest_rate", "c_inflation"}
    chain = [c.id for c in graph.prerequisite_chain("c_repo_rate")]
    assert chain == ["c_inflation", "c_interest_rate", "c_repo_rate"]
    assert graph.prerequisite_chain("c_missing") == []
    assert graph.is_acyclic()


def test_nearest(graph):
    best, score = graph.nearest([0, 0.6, 0.8])[0]
    assert best.id == "c_repo_rate" and score == pytest.approx(0.96, abs=1e-3)
    with pytest.raises(ValueError):
        graph.nearest([1, 0])
    assert ConceptGraph.empty().nearest([1, 0, 0]) == []


def test_sentence_around_picks_the_anchor_sentence():
    text = "Markets fell. The RBI held the repo rate at 6%. Bonds rallied."
    assert sentence_around(text, "repo rate", "held the ") == "The RBI held the repo rate at 6%."
    assert sentence_around(text, "missing") == "missing"


def test_plan_and_finish_links(graph):
    demands = [
        demand("d0", "Repo Rate"),  # alias
        demand("d1", "Policy rate"),  # candidates above the floor
        demand("d2", "Bitcoin"),  # nothing above the floor
        demand("d3", "SEBI order", type_="context"),  # context: never embedded
        demand("d4", "RBI", type_="context"),  # context but exact alias
    ]
    vectors = {"Policy rate": [0, 0.75, 0.66], "Bitcoin": [0.3, 0.3, 0.3]}
    plan = plan_links(graph, demands, vectors, {"p0": "The Policy rate rose."}, 0.9)
    assert plan.alias == {"d0": "c_repo_rate", "d4": "c_rbi"}
    assert [q.demand_id for q in plan.questions] == ["d1"]
    assert [c[0] for c in plan.questions[0].candidates] == ["c_repo_rate"]  # others < floor
    assert plan.questions[0].sentence == "The Policy rate rose."

    links = {lk.demand_id: lk for lk in finish_links(demands, plan, {0: "c_repo_rate"})}
    assert (links["d0"].target_id, links["d0"].method) == ("c_repo_rate", "alias")
    assert (links["d1"].target_id, links["d1"].method) == ("c_repo_rate", "confirmed")
    assert links["d2"].method == "unlinked" and links["d2"].score is not None
    assert links["d3"].target_id is None and links["d4"].target_id == "c_rbi"


def test_finish_links_ignores_ids_outside_candidates(graph):
    demands = [demand("d1", "Policy rate")]
    plan = plan_links(graph, demands, {"Policy rate": [0, 0.75, 0.66]}, {}, 0.9)
    links = finish_links(demands, plan, {0: "c_inflation"})  # not a candidate
    assert links[0].target_id is None and links[0].method == "unlinked"


async def test_link_demands_embeds_only_unmatched_labels_and_confirms(graph):
    embedded: list[list[str]] = []
    asked: list[list[str]] = []

    async def fake_embed(texts):
        embedded.append(texts)
        return [[0, 0.8, 0.6] for _ in texts]

    async def fake_confirm(questions):
        asked.append([q.phrase for q in questions])
        return {0: questions[0].candidates[0][0]}

    demands = [demand("d0", "Repo Rate"), demand("d1", "Policy rate", prefix="the ")]
    linked, links = await link_demands(
        graph,
        demands,
        {"p0": "We watch the Policy rate closely."},
        0.9,
        embed=fake_embed,
        confirm=fake_confirm,
    )
    assert embedded == [["Policy rate"]]
    assert asked == [["Policy rate"]]
    assert [d.target_id for d in linked] == ["c_repo_rate", "c_repo_rate"]
    assert [lk.method for lk in links] == ["alias", "confirmed"]


async def test_link_demands_degrades_to_alias_only_when_model_fails(graph):
    async def fake_embed(texts):
        return [[0, 0.8, 0.6] for _ in texts]

    async def failing_confirm(questions):
        raise llm.LLMUnavailable("down")

    demands = [demand("d0", "RBI"), demand("d1", "Policy rate")]
    linked, _ = await link_demands(
        graph, demands, {"p0": "x"}, 0.9, embed=fake_embed, confirm=failing_confirm
    )
    assert [d.target_id for d in linked] == ["c_rbi", None]


async def test_link_demands_noop_without_graph():
    demands = [demand("d0", "Inflation")]
    linked, _ = await link_demands(ConceptGraph.empty(), demands, {}, 0.9)
    assert linked[0].target_id is None


async def test_load_graph_from_local_file(tmp_path):
    path = tmp_path / "concepts.json"
    path.write_text(graph_file().model_dump_json())
    graph = await load_graph(str(path))
    assert len(graph) == 4 and graph.version == "test"
    assert len(await load_graph("")) == 0


async def test_load_graph_rejects_cycles(tmp_path):
    f = graph_file()
    f.concepts[0].prerequisites = ["c_repo_rate"]  # inflation <- repo rate <- inflation
    path = tmp_path / "concepts.json"
    path.write_text(f.model_dump_json())
    with pytest.raises(ValueError, match="cycles"):
        await load_graph(str(path))


# ---------------------------------------------------------------- taxonomy (M2.2, decision 33)


def test_taxonomy_is_the_only_domain_list_and_web_mirrors_it():
    import re
    from pathlib import Path

    from app.graph.models import DOMAINS
    from app.graph.taxonomy import BUSINESS_DOMAINS, DOMAIN_IDS

    assert DOMAINS == DOMAIN_IDS and len(DOMAINS) == 14
    assert BUSINESS_DOMAINS == ("economics", "finance", "business", "policy")
    web = Path(__file__).parents[2] / "web" / "src" / "lib" / "taxonomy.ts"
    block = re.search(r"DOMAINS = \[(.*?)\] as const", web.read_text(), re.S)
    assert block, "taxonomy.ts must declare DOMAINS"
    assert tuple(re.findall(r'"([a-z]+)"', block.group(1))) == DOMAIN_IDS
    # no other hard-coded domain list in the web app or API
    roots = [Path(__file__).parents[1] / "app", Path(__file__).parents[2] / "web" / "src"]
    four = re.compile(r'"economics",\s*"finance",\s*"business",\s*"policy"\s*[\])]')
    offenders = [
        str(p)
        for root in roots
        for p in root.rglob("*")
        if p.suffix in {".py", ".ts", ".tsx"}
        and four.search(p.read_text(encoding="utf-8"))
        and p.name not in {"taxonomy.py", "taxonomy.ts", "models.py"}
    ]
    assert offenders == []


def test_a_pre_m2_2_graph_file_with_four_domains_still_loads():
    from app.graph.graph import ConceptGraph
    from app.graph.models import ConceptGraphFile

    old = (
        '{"version": "2026-10-04", "domains": ["economics", "finance", "business", "policy"], '
        '"concepts": [{"id": "c_repo_rate", "label": "Repo rate", "domain": "economics", '
        '"definition": "d", "base_difficulty": 0.4, "embedding": [1.0, 0.0]}]}'
    )
    graph = ConceptGraph(ConceptGraphFile.model_validate_json(old))
    c = graph.get("c_repo_rate")
    assert c is not None and c.kind is None and c.jurisdiction == "global"
