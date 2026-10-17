"""Decision 70 Fix 3: explain a selection. A selection (paragraph offsets, never its text) is
matched by position to a term extracted on the page; no match means the paragraph's card."""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.content import router as read_router
from app.graph.loader import get_graph, set_graph
from app.ingest.models import Anchor, Demand, StoredParagraph
from app.main import app
from app.scoring import scorer
from app.scoring.scorer import ScoringInputs
from app.store.content_repo import InMemoryContentStore, set_content_store
from tests.fakes import auth
from tests.test_scorer import GRAPH, doc, state

P0 = "Rates on the bond rose as inflation and monetary_policy moved; the bond desk watched."
P1 = "The yield_curve inverted. " + "Filler words follow here. " * 6
NOW = datetime.now(UTC)


def at(text: str, part: str, nth: int = 0) -> tuple[int, int]:
    start = -1
    for _ in range(nth + 1):
        start = text.index(part, start + 1)
    return start, start + len(part)


def dem(did: str, target: str | None, pid: str, text: str, exact: str, nth: int = 0) -> Demand:
    start, end = at(text, exact, nth)
    return Demand(
        id=did,
        paragraph_id=pid,
        anchor=Anchor(
            exact=exact, prefix=text[max(0, start - 30) : start], suffix="", start=start, end=end
        ),
        type="concept",
        label=exact,
        target_id=target,
        salience=1.0,
        explained_in_text=False,
        zipf=3.0,
    )


DEMANDS = [
    dem("d_rates", None, "p0", P0, "Rates"),
    dem("d_bond", "c_bond", "p0", P0, "bond"),
    dem("d_infl", "c_inflation", "p0", P0, "inflation"),
    dem("d_mp", "c_monetary_policy", "p0", P0, "monetary_policy"),
    dem("d_bond2", "c_bond", "p0", P0, "bond", nth=1),
    dem("d_yc", "c_yield_curve", "p1", P1, "yield_curve"),
]
DOC = doc(
    DEMANDS,
    [
        StoredParagraph(id="p0", text=P0, structure=0.0),
        StoredParagraph(id="p1", text=P1, structure=0.0),
    ],
    content_id="art",
)


def lookup(pid: str, span: tuple[int, int]):
    hit = scorer.lookup(DOC, GRAPH, state(), NOW, ScoringInputs(), pid, *span)
    return hit.demand_id if hit else None


def test_a_selected_term_matches_its_own_demand():
    assert lookup("p0", at(P0, "inflation")) == "d_infl"


def test_a_phrase_around_a_term_matches_it():
    assert lookup("p0", at(P0, "as inflation and")) == "d_infl"


def test_a_selection_inside_a_longer_term_matches_it():
    assert lookup("p0", at(P0, "monetary")) == "d_mp"


def test_the_longest_term_inside_the_selection_wins():
    assert lookup("p0", at(P0, "inflation and monetary_policy")) == "d_mp"


def test_only_the_selected_occurrence_of_a_repeated_term_matches():
    assert lookup("p0", at(P0, "bond", 0)) == "d_bond"
    assert lookup("p0", at(P0, "bond", 1)) == "d_bond2"


def test_position_not_text_two_letters_inside_no_term_match_nothing():
    # "on" also appears inside "inflation" and "monetary_policy", but not where it was selected.
    assert lookup("p0", at(P0, "on the")) is None


def test_a_demand_without_a_concept_never_matches():
    assert lookup("p0", at(P0, "Rates")) is None


def test_another_paragraphs_term_never_matches():
    span = at(P1, "yield_curve")
    assert lookup("p1", span) == "d_yc"
    assert lookup("p0", span) != "d_yc"


# ------------------------------------------------------------------ route


@pytest.fixture
def client():
    store = InMemoryContentStore()
    store.docs["art"] = DOC
    set_content_store(store)
    read_router.reset_catalog()
    previous = get_graph()
    set_graph(GRAPH)
    yield TestClient(app, headers=auth("demo1", anonymous=True))
    set_graph(previous)
    set_content_store(None)
    read_router.reset_catalog()


def post(client, body, persona="newcomer"):
    return client.post(f"/v1/content/art/lookup?persona={persona}", json=body)


def test_route_returns_the_matched_note_and_writes_nothing(client, docs):
    client.get("/v1/content/art?persona=newcomer")  # the first request creates users/{uid} (auth)
    docs.written.clear()
    start, end = at(P0, "inflation")
    got = post(client, {"paragraph_id": "p0", "start": start, "end": end})
    assert got.status_code == 200
    a = got.json()["annotation"]
    assert a["id"] == "d_infl" and a["kind"] == "span" and a["concept_id"] == "c_inflation"
    assert a["anchor"]["exact"] == "inflation" and a["paragraph_id"] == "p0"
    assert docs.written == set()


def test_route_says_null_when_nothing_matches(client):
    start, end = at(P0, "Rates")
    got = post(client, {"paragraph_id": "p0", "start": start, "end": end}, persona="trader")
    assert got.status_code == 200 and got.json() == {"annotation": None}


def test_route_unknown_paragraph_is_404(client):
    assert post(client, {"paragraph_id": "p9", "start": 0, "end": 4}).status_code == 404


@pytest.mark.parametrize(
    ("start", "end"),
    [(-1, 4), (0, len(P0) + 1), (3, 4), (0, 121), (5, 5)],
)
def test_route_rejects_bad_offsets(client, start, end):
    pid = "p1" if end == 121 else "p0"  # p1 is long enough for a 121-character selection
    assert post(client, {"paragraph_id": pid, "start": start, "end": end}).status_code == 422


def test_route_never_takes_the_selected_text(client):
    start, end = at(P0, "inflation")
    body = {"paragraph_id": "p0", "start": start, "end": end, "text": "inflation"}
    assert post(client, body).status_code == 422
