"""M9 part 2, S2: prerequisite edges judged wrong are dropped where the API builds its graph."""

import json

from app.graph import refresh
from app.graph.build import slug_ids
from app.graph.graph import ConceptGraph
from app.graph.loader import get_graph, load_graph, set_graph
from app.graph.models import ConceptGraphFile
from app.graph.prereq_fixes import KNOWN_WRONG_PREREQS, without_known_wrong
from tests.test_growth import concept

# The labels behind each id, read from production on 2026-10-14 (a typo can't filter nothing).
LABELS = {
    "c_pfos": "PFOS", "c_phosita": "PHOSITA", "c_seizure_memo": "Seizure memo",
    "c_seizure": "Seizure", "c_humanoid_robot": "Humanoid robot", "c_mechanism": "Mechanism",
    "c_superforecaster": "Superforecaster",
    "c_macroeconomic_forecasting": "Macroeconomic forecasting",
    "c_education_minister": "Education Minister", "c_administration": "Administration",
    "c_c2_photorespiratory_carbon_pump": "C2 photorespiratory carbon pump",
    "c_carbon_cycle": "Carbon cycle", "c_franchise_t20_leagues": "Franchise T20 leagues",
    "c_franchise": "Franchise", "c_wearable_technology": "Wearable technology",
    "c_human_body": "Human body", "c_executive_magistrate": "Executive Magistrate",
    "c_proper_officer": "Proper officer",
    "c_circle_inspector_and_sub_inspector": "Circle Inspector and Sub-Inspector",
    "c_chief_election_commissioner": "Chief Election Commissioner",
    "c_elected_office": "Elected office", "c_permanent_account_number": "Permanent Account Number",
    "c_financial_account": "Financial account",
}  # fmt: skip


def test_every_listed_id_is_the_slug_of_its_production_label():
    ids = {i for edge in KNOWN_WRONG_PREREQS for i in edge}
    assert ids == set(LABELS) and len(KNOWN_WRONG_PREREQS) == 13
    for cid, label in LABELS.items():
        assert slug_ids([label])[0] == cid, (cid, label)


def pfos(prereqs):
    return concept("c_pfos", "PFOS").model_copy(update={"prerequisites": prereqs})


def test_only_the_listed_edges_go():
    out = without_known_wrong([pfos(["c_phosita", "c_chemistry"]), concept("c_x", "X")])
    assert out[0].prerequisites == ["c_chemistry"] and out[1] == concept("c_x", "X")


async def test_the_graph_file_is_filtered_at_load(tmp_path):
    graph_file = ConceptGraphFile(version="t", concepts=[
        concept("c_phosita", "PHOSITA"), concept("c_chemistry", "Chemistry"),
        pfos(["c_phosita", "c_chemistry"]),
    ])  # fmt: skip
    path = tmp_path / "concepts.json"
    path.write_text(json.dumps(graph_file.model_dump()))
    graph = await load_graph(str(path))
    assert graph.prerequisites("c_pfos") and [c.id for c in graph.prerequisites("c_pfos")] == [
        "c_chemistry"
    ]


def test_concepts_grown_elsewhere_are_filtered_when_merged_in():
    previous = get_graph()
    try:
        set_graph(
            ConceptGraph(ConceptGraphFile(version="t", concepts=[concept("c_phosita", "PHOSITA")]))
        )
        refresh.reset()
        refresh.get_refresher().apply([pfos(["c_phosita"])])
        assert get_graph().get("c_pfos").prerequisites == []
    finally:
        set_graph(previous)
        refresh.reset()
