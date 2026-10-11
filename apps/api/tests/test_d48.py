"""Decision 48: topics in the learning-goal and Describe-yourself boxes, and Redo setup."""

import asyncio
import json
import logging

import pytest
from fastapi.testclient import TestClient

from app import config, llm
from app.content import router as read_router
from app.graph import resolve as resolve_mod
from app.graph.graph import ConceptGraph
from app.graph.loader import get_graph, set_graph
from app.graph.models import Concept, ConceptGraphFile
from app.graph.taxonomy import DOMAIN_IDS
from app.main import app
from app.me import topic_match
from app.reader import goals as g
from app.reader import onboarding_text as ot
from app.reader import profile_edit as pe
from app.recs import feed as feed_mod
from app.recs import feed_router
from app.recs import web_search as ws
from app.store.content_repo import InMemoryContentStore, set_content_store
from app.store.docstore import get_doc_store
from app.store.reader_repo import ReaderRepo
from tests.fakes import auth, meta
from tests.test_onboarding_flow import Provider

DIM = 16
PHRASE = "electoral funding chaos"  # no concept, no alias, no word match: embedding only


def unit(i: int) -> list[float]:
    return [1.0 if j == i else 0.0 for j in range(DIM)]


def concept(cid, label, domain, freq, aliases=(), b=0.0):
    return Concept(id=cid, label=label, domain=domain, definition=".", base_difficulty=b,
                   doc_freq=freq, aliases=list(aliases), embedding=unit(15))  # fmt: skip


POLITICS = [
    concept("c_indian_national_congress", "Indian National Congress", "politics", 5),
    concept("c_lok_sabha", "Lok Sabha", "politics", 40),
    concept("c_party", "Party", "politics", 30),
    concept("c_coalition", "Coalition government", "politics", 20),
    concept("c_politics", "Politics", "politics", 50),
    *[concept(f"c_pol_{i}", f"Pol idea {i}", "politics", 10 - i) for i in range(10)],
    concept("c_seed_only", "Seed only", "politics", 0),
]
GRAPH = ConceptGraph(ConceptGraphFile(version="t", concepts=[
    *POLITICS,
    concept("c_inflation", "Inflation", "economics", 9),
    concept("c_cricket", "Cricket", "sports", 30),
]))  # fmt: skip


class Embed:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def __call__(self, texts, *, task_type, settings=None):
        self.calls.append(list(texts))
        topics = ot.topic_texts()
        vecs = [unit(topics.index(t)) if t in topics
                else unit(DOMAIN_IDS.index("politics")) if t == PHRASE else unit(15)
                for t in texts]  # fmt: skip
        return llm.EmbedResult(vecs, "fake", 1, 0.0)


class Confirm:
    def __init__(self) -> None:
        self.calls: list = []

    async def __call__(self, questions, run, ledger):
        self.calls.append([q.phrase for q in questions])
        return {}


class EditLLM:
    def __init__(self) -> None:
        self.output: dict = {"ops": []}

    async def __call__(self, task, schema, prompt_vars, **_):
        assert task == "profile_edit"
        return llm.LLMResult(schema.model_validate(self.output), meta(task=task))


@pytest.fixture
def env(monkeypatch):
    previous = get_graph()
    set_graph(GRAPH)
    set_content_store(InMemoryContentStore())
    read_router.reset_catalog()
    provider = Provider()
    web = ws.WebSearch({"article": provider, "video": provider, "podcast": provider},
                       ws.InMemoryRecCache(), ws.InMemorySearchCalls(), config.get_settings(),
                       frozenset())  # fmt: skip
    ws.set_web_search(web)
    feed_router.set_feed_search(feed_mod.FeedSearch(web))
    embed, confirm, edit = Embed(), Confirm(), EditLLM()
    monkeypatch.setattr(llm, "embed", embed)
    monkeypatch.setattr(resolve_mod, "confirm_links", confirm)
    monkeypatch.setattr(llm, "run_with_meta", edit)
    topic_match.reset_topic_vectors()
    yield {"embed": embed, "confirm": confirm, "edit": edit}
    feed_router.set_feed_search(None)
    ws.set_web_search(None)
    set_graph(previous)
    set_content_store(None)
    read_router.reset_catalog()
    topic_match.reset_topic_vectors()


def google(uid: str = "g1", version: str = "consent-v2") -> TestClient:
    c = TestClient(app, headers=auth(uid))
    assert c.post("/v1/me/consent", json={"version": version}).status_code == 200
    return c


def onboard(c: TestClient, interests=("economics", "sports"), comfort=None, frames=("software",)):
    body = {"field": "software", "interests": list(interests), "thinks_in": list(frames),
            "comfort": comfort or {}}  # fmt: skip
    assert c.post("/v1/onboarding", json=body).status_code == 200


def finished(uid: str = "g1", version: str = "consent-v1") -> TestClient:
    """An M7-era reader: old consent, comfort answers, onboarding finished."""
    c = google(uid, version)
    onboard(c, ("economics",), comfort={"economics": "comfortable"}, frames=("cricket",))
    assert c.post("/v1/calibration/skip").status_code == 200
    return c


def domain(docs, uid, d):
    return docs.docs.get(f"users/{uid}/domains/{d}", {})


# ---------------------------------------------------------------- topic goals (pure)


def test_topic_targets_whole_words_label_word_ignored_then_most_read():
    ids = [c.id for c in g.topic_targets(GRAPH, "politics", "Indian party politics")]
    # "indian" and "party" match whole words; "politics" is the topic's own label word
    assert ids[:2] == ["c_party", "c_indian_national_congress"]
    assert len(ids) == 10 and "c_seed_only" not in ids  # filled with met concepts first
    assert ids[2:4] == ["c_politics", "c_lok_sabha"]  # most read
    assert "c_party" not in [c.id for c in g.topic_targets(GRAPH, "politics", "art")][:1]
    assert ot.tokens("Party") == {"party"} and "art" not in ot.tokens("Party")


# ---------------------------------------------------------------- goals (routes)


def test_goal_preview_of_a_topic_alias_makes_no_model_call_and_writes_nothing(env, docs):
    c = google()
    body = c.post(
        "/v1/me/goals/preview", json={"type": "learning", "text": "understand Indian politics"}
    ).json()
    assert body["kind"] == "topic" and body["topic"] == "politics" and body["label"] == "Politics"
    assert body["targets"][0]["concept_id"] == "c_indian_national_congress"
    assert len(body["targets"]) == 10
    assert env["embed"].calls == [] and env["confirm"].calls == []
    assert not [k for k in docs.docs if "/goals/" in k]
    day = feed_mod.today_utc()
    assert docs.docs[f"users/g1/goal_resolve_counts/{day}"]["count"] == 1


def test_saving_a_previewed_goal_revalidates_ids_and_stores_no_text(env, docs, caplog):
    caplog.set_level(logging.DEBUG)
    c = google()
    prev = c.post(
        "/v1/me/goals/preview", json={"type": "learning", "text": "Indian politics"}
    ).json()
    ids = [t["concept_id"] for t in prev["targets"]]
    save = {"type": "learning_resolved", "kind": "topic", "topic": "politics", "target_ids": ids}
    out = c.post("/v1/me/goals", json=save)
    assert out.status_code == 200 and out.json()["kind"] == "topic" and out.json()["total"] == 10
    day = feed_mod.today_utc()
    assert docs.docs[f"users/g1/goal_resolve_counts/{day}"]["count"] == 1  # save is free
    stored = json.dumps({k: v for k, v in docs.docs.items() if "/goals/" in k}, default=str)
    logged = " ".join(r.getMessage() + json.dumps(r.__dict__, default=str) for r in caplog.records)
    assert "Indian politics" not in stored and "indian politics" not in stored.casefold()
    assert "Indian politics" not in logged
    bad = [{**save, "target_ids": ["c_inflation"]},  # wrong topic
           {**save, "target_ids": ["c_nope"]},  # unknown
           {"type": "learning_resolved", "kind": "concept", "concept_id": "c_inflation",
            "target_ids": ["c_party"]}]  # fmt: skip
    for body in bad:
        assert c.post("/v1/me/goals", json=body).status_code == 422


def test_one_step_create_resolves_topics_too_and_embeds_a_phrase_once(env):
    c = google()
    out = c.post("/v1/me/goals", json={"type": "learning", "text": PHRASE})
    assert out.status_code == 200 and out.json()["label"] == "Politics"
    reader = [t for call in env["embed"].calls for t in call if t not in ot.topic_texts()]
    assert reader == [PHRASE]  # resolve_names and the topic fallback share one embedding


# ---------------------------------------------------------------- Describe yourself: set_interest


def _more(topic="Indian politics", direction="read_more"):
    return {"ops": [{"op": direction, "topic": topic}]}


def test_set_interest_previews_applies_and_undoes(env, docs):
    c = google()
    onboard(c, ("economics",))
    env["edit"].output = _more()
    r = c.post(
        "/v1/me/profile/edits", json={"text": "I want to learn about Indian politics"}
    ).json()
    assert r["preview"]["interests"] == [{"domain": "politics", "direction": "more"}]
    assert domain(docs, "g1", "politics")["interest"] == 0.3  # preview writes nothing
    assert c.post(f"/v1/me/profile/edits/{r['edit_id']}/apply").status_code == 200
    assert domain(docs, "g1", "politics")["interest"] == 1.0
    assert "politics" in c.get("/v1/feed").json()["topics"]
    edit = docs.docs[f"users/g1/profile_edits/{r['edit_id']}"]
    assert edit["deltas"]["interest"] == {"politics": [0.3, 1.0]}
    assert "Indian politics" not in json.dumps(edit, default=str)
    assert c.post(f"/v1/me/profile/edits/{r['edit_id']}/undo").status_code == 200
    assert domain(docs, "g1", "politics")["interest"] == 0.3


def test_set_interest_undo_never_undoes_a_later_change(env, docs):
    c = google()
    onboard(c, ("economics",))
    env["edit"].output = _more("cricket", "read_less")
    onboard(c, ("economics", "sports"))  # sports chosen: 1.0
    r = c.post("/v1/me/profile/edits", json={"text": "less cricket"}).json()
    c.post(f"/v1/me/profile/edits/{r['edit_id']}/apply")
    assert domain(docs, "g1", "sports")["interest"] == 0.3
    # A later change (e.g. an onboarding pick) leaves 0.85: a blind restore would write 1.0.
    docs.docs["users/g1/domains/sports"] = domain(docs, "g1", "sports") | {"interest": 0.85}
    c.post(f"/v1/me/profile/edits/{r['edit_id']}/undo")
    assert domain(docs, "g1", "sports")["interest"] == 0.85


def test_set_interest_limits_unresolved_and_demo(env, docs):
    c = google()
    onboard(c)
    env["edit"].output = {"ops": [{"op": "read_more", "topic": f"t{i} politics"} for i in range(4)]}
    r = c.post("/v1/me/profile/edits", json={"text": "x"})
    assert r.status_code == 422 and r.json()["error"] == "too_many_topics"
    assert env["embed"].calls == []  # rejected before any embedding
    env["edit"].output = _more("c_politics")
    assert (
        c.post("/v1/me/profile/edits", json={"text": "x"}).json()["error"]
        == "concept_id_from_model"
    )
    env["edit"].output = _more("zz unknown thing")
    p = c.post("/v1/me/profile/edits", json={"text": "x"}).json()["preview"]
    assert p["interests"] == [] and p["unresolved"] == ["zz unknown thing"]
    demo = TestClient(app, headers=auth("demo", anonymous=True))
    env["edit"].output = _more()
    d = demo.post("/v1/me/profile/edits?persona=newcomer", json={"text": "x"}).json()
    assert (
        d["preview"]["interests"] == []
        and d["preview"]["note"] == "Feed topics are fixed in the demo."
    )
    demo.post(f"/v1/me/profile/edits/{d['edit_id']}/apply?persona=newcomer")
    assert not [k for k in docs.docs if k.startswith("users/demo/domains/")]


def test_edits_stored_before_decision_48_still_load():
    old = {"concepts": {"c_x": True}, "domains": {}, "settings": {"density": "minimal"}}
    assert pe.Resolved.from_doc(old).interests == {}
    assert pe.interests_from_doc({"edges": {}, "theta": {}}) == {}


# ---------------------------------------------------------------- Redo setup


def test_redo_guards():
    demo = TestClient(app, headers=auth("demo", anonymous=True))
    assert demo.post("/v1/onboarding/redo").status_code == 403
    assert TestClient(app, headers=auth("nc")).post("/v1/onboarding/redo").status_code == 409
    fresh = google("fresh")
    assert fresh.post("/v1/onboarding/redo").json()["detail"] == "onboarding_not_done"


def test_redo_reruns_both_screens_and_deletes_nothing(env, docs):
    c = finished()
    user = docs.docs["users/g1"]
    theta_before = domain(docs, "g1", "economics")["theta"]
    calibration_before = user["calibration"]
    prof = c.get("/v1/me/profile").json()["onboarding"]
    assert prof["consent_version"] == "consent-v1" and prof["redo"] is None
    assert c.post("/v1/onboarding/redo").json() == {"redo": "about"}
    assert docs.docs["users/g1"]["onboarding_done"] is True  # never gated
    assert c.get("/v1/me/profile").json()["onboarding"]["redo"] == "about"
    onboard(c, ("politics", "sports"), frames=("software",))
    user = docs.docs["users/g1"]
    assert user["onboarding_done"] is True and user["onboarding_redo"] == "discover"
    assert user["calibration"] == calibration_before
    assert user["onboarding"]["comfort"] == {"economics": "comfortable"}  # kept
    assert user["thinks_in"] == ["cricket", "software"]  # kept, the field's frame added
    assert domain(docs, "g1", "economics")["theta"] == theta_before  # θ untouched
    assert domain(docs, "g1", "politics")["interest"] == 1.0
    items = c.post("/v1/onboarding/discover", json={"topics": ["politics"]}).json()["items"]
    assert items
    assert (
        c.post("/v1/onboarding/pick", json={"item_id": items[0]["id"], "liked": True}).status_code
        == 200
    )
    assert c.post("/v1/onboarding/finish").json() == {"done": True}
    assert docs.docs["users/g1"]["onboarding_redo"] is None
    assert c.post("/v1/onboarding/discover", json={"topics": ["politics"]}).status_code == 409


def test_redo_cancel_clears_only_its_state(env, docs):
    c = finished()
    c.post("/v1/onboarding/redo")
    onboard(c, ("politics",))
    c.post("/v1/onboarding/discover", json={"topics": ["politics"]})
    assert docs.docs["users/g1"]["onboarding_offered"]
    assert c.post("/v1/onboarding/redo/cancel").json() == {"redo": None}
    user = docs.docs["users/g1"]
    assert user["onboarding_redo"] is None and user["onboarding_offered"] == {}
    assert user["onboarding_done"] is True and domain(docs, "g1", "politics")["interest"] == 1.0
    assert c.post("/v1/onboarding/discover", json={"topics": ["politics"]}).status_code == 409


def test_repo_pick_and_know_are_open_during_redo(docs):
    repo = ReaderRepo(get_doc_store())

    async def run():
        async def seed(t):
            offered = {"i1": {"topic": "politics", "concept": "c_party"}}
            t.set(
                "users/r1",
                {
                    "consent": {"version": "consent-v1"},
                    "onboarding_done": True,
                    "onboarding_redo": "discover",
                    "onboarding_offered": offered,
                },
            )

        await get_doc_store().run(seed)
        pick = await repo.onboarding_pick("r1", "i1", True, 9, lambda v: v + 0.15)
        from app.reader.events import ConceptRef

        know = await repo.onboarding_know("r1", "c_party", True, ConceptRef("politics", 0.0),
                                          lambda e, th: (pe_edge(), th), 9)  # fmt: skip
        return pick, know

    def pe_edge():
        from datetime import UTC, datetime

        from app.reader import model

        return model.init_edge(0.5, datetime.now(UTC))

    assert asyncio.run(run()) == ("ok", "ok")


def test_an_acronym_term_needs_capitals_in_the_text():
    from app.reader import onboarding

    oct_ = concept("c_oct", "OCT", "politics", 3)
    assert not onboarding.as_written(oct_, "The week in politics (Oct. 7, 2026)")
    assert onboarding.as_written(oct_, "OCT rules changed")
    assert onboarding.as_written(concept("c_party", "Party", "politics", 3), "party")


def test_interest_edit_summary_and_no_op_lines(env, docs):
    c = google()
    onboard(c, ("economics",))
    env["edit"].output = _more()
    r = c.post("/v1/me/profile/edits", json={"text": "more Indian politics"}).json()
    c.post(f"/v1/me/profile/edits/{r['edit_id']}/apply")
    history = c.get("/v1/me/profile/edits").json()["edits"]
    assert history[0]["interests"] == [{"domain": "politics", "direction": "more"}]
    # "less" on a topic that is already out of the feed changes nothing: no line, no edit field
    env["edit"].output = _more("cricket", "read_less")
    p = c.post("/v1/me/profile/edits", json={"text": "less cricket"}).json()["preview"]
    assert p["interests"] == []
