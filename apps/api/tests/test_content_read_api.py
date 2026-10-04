import pytest
from fastapi.testclient import TestClient

from app import config
from app.content import router as read_router
from app.graph.graph import ConceptGraph
from app.graph.loader import get_graph, set_graph
from app.graph.models import ConceptGraphFile
from app.main import app
from app.store.content_repo import InMemoryContentStore, set_content_store
from tests.fakes import auth
from tests.test_placeholder_scorer import GRAPH, demand, doc, paras


def article(cid, title, site, demands):
    d = doc(demands, paras(2, 200)).model_copy(
        update={"content_id": cid, "title": title, "site": site}
    )
    return d


@pytest.fixture
def client():
    store = InMemoryContentStore()
    store.docs["a1"] = article(
        "a1", "Bond yields climb", "mint", [demand("d1", "c_yield_curve", pid="p0")]
    )
    store.docs["a2"] = article("a2", "Budget deficit widens", "businessline", [])
    set_content_store(store)
    read_router.reset_catalog()
    previous = get_graph()
    set_graph(GRAPH)
    yield TestClient(app, headers=auth("demo", anonymous=True))
    set_graph(previous)
    set_content_store(None)
    read_router.reset_catalog()


def test_list_and_search(client):
    body = client.get("/v1/content").json()
    assert [i["id"] for i in body] == ["a1", "a2"]
    assert body[0] == {
        "id": "a1",
        "title": "Bond yields climb",
        "site": "mint",
        "word_count": 400,
        "description": None,
        "author": None,
        "published": None,
        "image": None,
        "domain": "finance",
        "concepts_new": 1,
    }
    assert [i["id"] for i in client.get("/v1/content?q=DEFICIT").json()] == ["a2"]
    assert [i["id"] for i in client.get("/v1/content?q=businessline").json()] == ["a2"]


def test_detail_and_404(client):
    body = client.get("/v1/content/a1").json()
    assert body["title"] == "Bond yields climb" and [p["id"] for p in body["paragraphs"]] == [
        "p0",
        "p1",
    ]
    assert client.get("/v1/content/nope").status_code == 404
    assert client.get("/v1/content/nope/annotations").status_code == 404


def test_annotations_shape(client):
    body = client.get("/v1/content/a1/annotations?persona=newcomer&density=guided").json()
    assert body["persona"] == "newcomer" and body["density"] == "guided" and body["count"] == 1
    item = body["annotations"][0]
    assert item["kind"] == "span" and item["concept_id"] == "c_yield_curve"
    assert item["domain"] == "finance"
    assert item["prerequisites"] == ["Bond"] and item["anchor"]["exact"] == "yield_curve"
    assert item["debug"] is None


@pytest.mark.parametrize("query", ["persona=engineer", "density=dense"])
def test_rejects_unknown_persona_or_density(client, query):
    assert client.get(f"/v1/content/a1/annotations?{query}").status_code == 422


def test_debug_only_in_dev(client, monkeypatch):
    item = client.get("/v1/content/a1/annotations?debug=1").json()["annotations"][0]
    assert set(item["debug"]) == {"p_know", "salience", "span_score", "domain", "base_difficulty"}
    assert item["debug"]["domain"] == "finance"
    monkeypatch.setenv("ENV", "prod")
    config.get_settings.cache_clear()
    item = client.get("/v1/content/a1/annotations?debug=1").json()["annotations"][0]
    assert item["debug"] is None


def test_empty_graph_gives_no_annotations(client):
    set_graph(ConceptGraph(ConceptGraphFile(version="e", concepts=[])))
    assert client.get("/v1/content/a1/annotations").json()["count"] == 0


def test_list_counts_are_per_persona_and_density(client):
    def new_for(query):
        return client.get(f"/v1/content?{query}").json()[0]["concepts_new"]

    # yield curve (finance, b=1, prereq bond): newcomer misses it, the trader knows it
    assert new_for("persona=newcomer") == 1
    assert new_for("persona=trader&density=minimal") == 0
    assert client.get("/v1/content?persona=nobody").status_code == 422


def test_detail_carries_publisher_metadata(client):
    from app.store.content_repo import get_content_store

    store = get_content_store()
    store.docs["a1"] = store.docs["a1"].model_copy(
        update={"description": "Standfirst.", "author": "A. Writer", "published": "2026-10-01"}
    )
    body = client.get("/v1/content/a1").json()
    assert (body["description"], body["author"], body["published"]) == (
        "Standfirst.",
        "A. Writer",
        "2026-10-01",
    )
    assert body["domain"] == "finance"
