"""2-screen onboarding (decisions 41, 42): resolve, discover, pick, know, finish.

The privacy tests matter most: free text never reaches search, logs or Firestore; models see
only individual redacted pieces that had no exact match.
"""

import json
import logging
from datetime import UTC, datetime

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
from app.reader import model, onboarding
from app.reader import onboarding_text as ot
from app.recs import feed as feed_mod
from app.recs import feed_rank as fr
from app.recs import feed_router
from app.recs import web_search as ws
from app.recs.feed import reader_topics
from app.recs.models import WebResult
from app.store.content_repo import InMemoryContentStore, set_content_store
from app.store.reader_repo import USER_SUBCOLLECTIONS
from tests.fakes import auth
from tests.test_scorer import demand, doc

DIM = 16


def unit(i: int) -> list[float]:
    return [1.0 if j == i else 0.0 for j in range(DIM)]


def concept(cid: str, label: str, domain: str, b: float, aliases=()) -> Concept:
    return Concept(id=cid, label=label, domain=domain, definition=f"{label}.", base_difficulty=b,
                   aliases=list(aliases), embedding=unit(14))  # fmt: skip


GRAPH = ConceptGraph(ConceptGraphFile(version="t", concepts=[
    concept("c_inflation", "Inflation", "economics", 0.0),
    concept("c_bond", "Bond", "finance", 1.0, aliases=["bonds"]),
    concept("c_ma", "Mergers and acquisitions", "business", 0.5, aliases=["M&A"]),
]))  # fmt: skip

SECRET = ["Formula racing", "price rises", "zz unknown thing", "me@example.com"]


class Embed:
    """llm.embed: topic scope lines are unit vectors 0–13; 'Formula racing' sits on sports,
    'price rises' near the graph's concepts (14), anything else on 15 (near nothing)."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def __call__(self, texts, *, task_type, settings=None):
        self.calls.append(list(texts))
        topics = ot.topic_texts()
        vecs = []
        for t in texts:
            if t in topics:
                vecs.append(unit(topics.index(t)))
            elif t == "Formula racing":
                vecs.append(unit(DOMAIN_IDS.index("sports")))
            elif t in ("price rises", "rising prices"):
                vecs.append(unit(14))
            else:
                vecs.append(unit(15))
        return llm.EmbedResult(vecs, "fake-embed", 10, 0.00001)


class Confirm:
    def __init__(self) -> None:
        self.questions: list = []
        self.calls: list[list] = []

    async def __call__(self, questions, run, ledger):
        self.calls.append(list(questions))
        self.questions += list(questions)
        return {i: "c_bond" if q.phrase == "price rises" else None for i, q in enumerate(questions)}


class Provider:
    """One article per query whose title names the query and whose snippet names two
    concepts (so items get Know this? terms)."""

    name = "fake"
    formats = frozenset({"article", "video", "podcast"})

    def __init__(self, empty: bool = False) -> None:
        self.queries: list[str] = []
        self.empty = empty

    async def search(self, query, fmt, news=False, include_domains=()):
        self.queries.append(query)
        if self.empty:
            return []
        slug = query.replace(" ", "-") + "-today"
        host = include_domains[0] if include_domains else "x.test"  # the fallback: a wire
        return [WebResult(url=f"https://{host}/{fmt}/{slug}", title=f"{query} today",
                          snippet="Inflation and bonds explained", source=host,
                          format=fmt)]  # fmt: skip


@pytest.fixture
def env(monkeypatch):
    previous = get_graph()
    set_graph(GRAPH)
    store = InMemoryContentStore()
    set_content_store(store)
    read_router.reset_catalog()
    provider = Provider()
    web = ws.WebSearch({"article": provider, "video": provider, "podcast": provider},
                       ws.InMemoryRecCache(), ws.InMemorySearchCalls(), config.get_settings(),
                       frozenset())  # fmt: skip
    ws.set_web_search(web)
    feed_router.set_feed_search(feed_mod.FeedSearch(web))
    embed, confirm = Embed(), Confirm()
    monkeypatch.setattr(llm, "embed", embed)
    monkeypatch.setattr(resolve_mod, "confirm_links", confirm)
    topic_match.reset_topic_vectors()

    async def no_llm(*a, **k):
        raise AssertionError("no other model call in onboarding")

    monkeypatch.setattr(llm, "run_with_meta", no_llm)
    yield {"provider": provider, "web": web, "embed": embed, "confirm": confirm, "store": store}
    feed_router.set_feed_search(None)
    ws.set_web_search(None)
    set_graph(previous)
    set_content_store(None)
    read_router.reset_catalog()
    topic_match.reset_topic_vectors()


def google(uid: str = "g1", consent: bool = True) -> TestClient:
    c = TestClient(app, headers=auth(uid))
    if consent:
        assert c.post("/v1/me/consent", json={"version": "consent-v2"}).status_code == 200
    return c


def onboard(c: TestClient, interests=("economics", "sports")) -> None:
    body = {"field": "software", "interests": list(interests), "thinks_in": ["software"]}
    resp = c.post("/v1/onboarding", json=body)
    assert resp.status_code == 200 and resp.json()["next"] == "discover"


# ---------------------------------------------------------------- pure logic


def test_pieces_split_trim_dedupe_and_cap():
    assert ot.pieces(" F1 ,startups,, f1 , Indian politics.") == ["F1", "startups",
                                                                  "Indian politics"]  # fmt: skip
    assert len(ot.pieces(",".join(f"p{i}" for i in range(9)))) == ot.MAX_PIECES
    long = ot.pieces("a very long phrase that keeps going on and on past forty chars")[0]
    assert len(long) <= ot.MAX_PIECE_CHARS and not long.endswith(" ")


def test_the_alias_list_covers_every_topic_with_valid_ids():
    topics = set(ot.ONBOARDING_TOPIC_ALIASES.values())
    assert topics == set(DOMAIN_IDS)
    assert all(k == k.casefold().strip() for k in ot.ONBOARDING_TOPIC_ALIASES)
    for phrase, topic in [("IPL", "sports"), ("Champions League", "sports"), ("LLMs", "technology"),
                          ("EVs", "technology"), ("UPSC", "education"), ("ISRO", "science"),
                          ("elections", "politics"), ("mental health", "health")]:  # fmt: skip
        assert ot.alias_topic(phrase) == topic


def test_word_chunks_drop_stop_generic_and_country_words():
    assert ot.word_chunks("Latest news on inflation in India") == [("inflation", 1)]
    chunks = ot.word_chunks("China's foreign relations")
    assert chunks == [("foreign relations", 2), ("foreign", 1), ("relations", 1)]
    assert ot.word_chunks("quarterly earnings of companies")[0] == ("quarterly earnings", 2)


def test_word_topic_prefers_two_word_chunks_and_skips_generic_seed_words():
    def c(cid, label, domain, freq):
        return Concept(id=cid, label=label, domain=domain, definition=".", base_difficulty=0.0,
                       doc_freq=freq, embedding=unit(14))  # fmt: skip

    graph = ConceptGraph(ConceptGraphFile(version="t", concepts=[
        c("c_black_hole", "Black hole", "science", 0), c("c_black", "Black", "culture", 50),
        c("c_column", "Column", "culture", 0), c("c_inflation", "Inflation", "economics", 9),
    ]))  # fmt: skip
    hole = ot.word_topic(graph, "black holes")
    assert (hole.topic, hole.via) == ("science", "c_black_hole")  # not "Black" (one word)
    assert ot.word_topic(graph, "my column") is None  # one seed-only word: too generic
    assert ot.word_topic(graph, "weekend plans") is None
    assert ot.word_topic(graph, "inflation news in India").topic == "economics"
    music = ot.word_topic(graph, "Indian classical music")
    assert (music.topic, music.via) == ("culture", "alias")


def test_resolve_word_match_makes_no_model_call(env):
    body = google("g2").post("/v1/onboarding/resolve", json={"text": "cricket highlights"}).json()
    assert body["topics"] == [{"phrase_index": 0, "phrase": "cricket highlights",
                               "topic": "sports", "via": "words"}]  # fmt: skip
    assert env["embed"].calls == [] and env["confirm"].questions == []


def test_aliases_and_nearest_topic():
    assert ot.alias_topic(" Formula  One ") == "sports" and ot.alias_topic("VC") == "business"
    assert ot.alias_topic("knitting") is None
    scopes = [unit(i) for i in range(len(DOMAIN_IDS))]
    assert ot.nearest_topic(unit(DOMAIN_IDS.index("law")), scopes, 0.86) == ("law", 1.0)
    assert ot.nearest_topic(unit(15), scopes, 0.86) is None


def test_offer_keeps_terms_stable_excludes_resolved_and_caps():
    items = [("a", "economics", ["c1", "c2"]), ("b", "economics", ["c1", "c2"]),
             ("c", "economics", ["c1", "c2"])]  # fmt: skip
    got = onboarding.offer({}, items, excluded=["c2"])
    assert got == {"a": {"topic": "economics", "concept": "c1"},
                   "b": {"topic": "economics", "concept": None},
                   "c": {"topic": "economics", "concept": None}}  # fmt: skip
    again = onboarding.offer(got, [("a", "economics", ["c9"])], excluded=[])
    assert again["a"]["concept"] == "c1"  # stable across re-asks
    many = [(f"i{n}", "sports", [f"t{n}"]) for n in range(40)]
    capped = onboarding.offer({}, many, excluded=[])
    assert len(capped) == onboarding.MAX_OFFERED_ITEMS
    assert sum(v["concept"] is not None for v in capped.values()) == onboarding.MAX_OFFERED_TERMS


def test_terms_come_from_the_items_topic_corpus_concepts_first():
    def c(cid, domain, b, freq):
        return Concept(id=cid, label=cid, domain=domain, definition=".", base_difficulty=b,
                       doc_freq=freq, embedding=unit(14))  # fmt: skip

    named = [c("c_column", "culture", 0.0, 9), c("c_seed", "sports", 0.0, 0),
             c("c_far", "sports", 2.0, 5), c("c_near", "sports", 0.2, 5)]  # fmt: skip
    assert onboarding.term_order(named, "sports", {"sports": 0.0}) == ["c_near", "c_far", "c_seed"]


def test_interests_with_picks_apply_deltas_and_clamp():
    picks = {"x": {"topic": "sports", "liked": False}, "y": {"topic": "sports", "liked": False},
             "z": {"topic": "economics", "liked": True}}  # fmt: skip
    got = onboarding.interests_with_picks(["sports", "economics"], picks)
    assert got["sports"] == pytest.approx(0.7) and got["economics"] == 1.0
    assert got["law"] == onboarding.INTEREST_OTHER


def test_mix_gives_every_group_a_card_first_articles_first():
    def cand(url, topic, fmt="article"):
        return fr.FeedCandidate(WebResult(url=url, title="t", source="s", format=fmt), topic)

    a = [cand("a-video", "sports", "video"), cand("a1", "sports"), cand("a2", "sports")]
    b = [cand("b1", "law")]
    got = fr.onboarding_mix([a, b], datetime.now(UTC), 3)
    assert [c.result.url for c in got] == ["a1", "b1", "a2"]


# ---------------------------------------------------------------- resolve


def test_resolve_maps_concepts_aliases_and_topics(env):
    c = google()
    body = c.post(
        "/v1/onboarding/resolve",
        json={"text": "Inflation, F1, price rises, Formula racing, zz unknown thing"},
    ).json()
    assert {x["id"] for x in body["concepts"]} == {"c_inflation", "c_bond"}
    assert body["topics"] == [
        {"phrase_index": 1, "phrase": "F1", "topic": "sports", "via": "alias"},
        {"phrase_index": 3, "phrase": "Formula racing", "topic": "sports", "via": "embedding"},
    ]
    assert body["unrecognised"] == ["zz unknown thing"]


def test_resolve_privacy_nothing_reaches_search_logs_or_store(env, caplog, docs):
    caplog.set_level(logging.DEBUG)
    c = google()
    text = "Formula racing, price rises, zz unknown thing, me@example.com"
    assert c.post("/v1/onboarding/resolve", json={"text": text}).status_code == 200
    # (a) no search at all during resolve
    assert env["provider"].queries == []
    # (b) models see only individual redacted pieces with no exact match, never the full text
    embedded = [t for call in env["embed"].calls for t in call if t not in ot.topic_texts()]
    assert set(embedded) == {"Formula racing", "price rises", "zz unknown thing", "[email]"}
    assert all(text not in t and "me@example.com" not in t for t in embedded)
    asked = [q.phrase for q in env["confirm"].questions]
    assert asked == ["price rises"]  # the only piece with candidates above the threshold
    assert all(q.sentence.endswith(q.phrase) for q in env["confirm"].questions)
    # (c) no log record and no stored document carries any piece
    logged = " ".join(f"{r.getMessage()} {json.dumps(r.__dict__, default=str)}"
                      for r in caplog.records)  # fmt: skip
    stored = json.dumps(docs.docs, default=str)
    for piece in SECRET:
        assert piece not in logged and piece not in stored


def test_each_piece_reaches_the_model_alone(env):
    """Two pieces with candidates: each link_confirm prompt and each embed request carries one
    piece only (the 14 topic scope lines are embedded on their own, once)."""
    text = "price rises, rising prices, Formula racing"
    assert google().post("/v1/onboarding/resolve", json={"text": text}).status_code == 200
    asked = [[q.phrase for q in call] for call in env["confirm"].calls]
    assert asked == [["price rises"], ["rising prices"]]
    topics = set(ot.topic_texts())
    reader = [[t for t in call if t not in topics] for call in env["embed"].calls]
    assert all(len(r) <= 1 for r in reader)
    assert sorted(t for r in reader for t in r) == ["Formula racing", "price rises",
                                                    "rising prices"]  # fmt: skip


def test_exact_matches_make_no_model_call_and_whole_piece_comes_first(env):
    c = google()
    body = c.post(
        "/v1/onboarding/resolve", json={"text": "mergers and acquisitions, F1, inflation & bonds"}
    ).json()
    assert {x["id"] for x in body["concepts"]} == {"c_ma", "c_inflation", "c_bond"}
    assert body["topics"][0]["via"] == "alias" and body["unrecognised"] == []
    assert env["embed"].calls == [] and env["confirm"].questions == []


def test_resolve_guards_and_cap(env, monkeypatch):
    assert google("nc", consent=False).post(
        "/v1/onboarding/resolve", json={"text": "F1"}).status_code == 409  # fmt: skip
    demo = TestClient(app, headers=auth("demo", anonymous=True))
    assert demo.post("/v1/onboarding/resolve", json={"text": "F1"}).status_code == 403
    monkeypatch.setattr(config.get_settings(), "onboarding_resolve_daily_cap", 1)
    c = google()
    assert c.post("/v1/onboarding/resolve", json={"text": "F1"}).status_code == 200
    assert c.post("/v1/onboarding/resolve", json={"text": "F1"}).status_code == 429
    too_long = c.post("/v1/onboarding/resolve", json={"text": "x" * 121})
    assert too_long.status_code == 422


def test_an_embedding_outage_leaves_pieces_unrecognised(env, monkeypatch):
    async def down(*a, **k):
        raise llm.LLMUnavailable("down")

    monkeypatch.setattr(llm, "embed", down)
    body = google().post("/v1/onboarding/resolve", json={"text": "Formula racing, F1"}).json()
    assert body["unrecognised"] == ["Formula racing"] and body["topics"][0]["phrase"] == "F1"


# ---------------------------------------------------------------- discover


def test_discover_queries_are_only_labels_plus_fixed_phrases(env):
    c = google()
    onboard(c)
    resp = c.post("/v1/onboarding/discover",
                  json={"topics": ["economics", "sports"], "concepts": ["c_bond"]})  # fmt: skip
    assert resp.status_code == 200
    allowed = {feed_mod.feed_query(t, f) for t in ("economics", "sports")
               for f in ("article", "video", "podcast")} | {"Bond news this week"}  # fmt: skip
    assert set(env["provider"].queries) == allowed  # 6 topic + 1 concept search
    items = resp.json()["items"]
    assert 1 <= len(items) <= onboarding.DISCOVER_ITEMS
    assert {i["topic"] for i in items} >= {"economics", "sports", "finance"}
    assert items[0]["format"] == "article"


def test_discover_shares_the_cache_and_counts_only_calls_that_search(env, monkeypatch, docs):
    monkeypatch.setattr(config.get_settings(), "onboarding_discover_daily_cap", 1)
    a = google("ga")
    onboard(a)
    a.post("/v1/onboarding/discover", json={"topics": ["economics"]})
    searched = len(env["provider"].queries)
    a.post("/v1/onboarding/discover", json={"topics": ["economics"]})  # cached: free
    b = google("gb")
    onboard(b)
    b.post("/v1/onboarding/discover", json={"topics": ["economics"]})  # shared cache
    assert len(env["provider"].queries) == searched
    day = feed_mod.today_utc()
    assert docs.docs[f"users/ga/onboarding_discover_counts/{day}"]["count"] == 1
    assert f"users/gb/onboarding_discover_counts/{day}" not in docs.docs
    a.post("/v1/onboarding/discover", json={"topics": ["law"]})  # over the reader's limit
    assert len(env["provider"].queries) == searched


def test_discover_validates_concepts_and_the_concept_sub_cap(env, monkeypatch):
    c = google()
    onboard(c)
    assert c.post("/v1/onboarding/discover", json={"concepts": ["c_nope"]}).status_code == 422
    three = {"concepts": ["c_bond", "c_inflation", "c_ma"]}
    assert c.post("/v1/onboarding/discover", json=three).status_code == 422
    assert c.post("/v1/onboarding/discover", json={}).status_code == 422
    monkeypatch.setattr(config.get_settings(), "onboarding_concept_search_daily_cap", 0)
    c.post("/v1/onboarding/discover", json={"topics": ["law"], "concepts": ["c_bond"]})
    assert "Bond news this week" not in env["provider"].queries


def test_discover_falls_back_to_library_items(env):
    env["provider"].empty = True
    lib = doc([demand("d1", "c_inflation")], content_id="lib1")
    env["store"].docs["lib1"] = lib
    read_router.reset_catalog()
    c = google()
    onboard(c)
    items = c.post("/v1/onboarding/discover", json={"topics": ["economics"]}).json()["items"]
    assert [(i["id"], i["kind"], i["content_id"]) for i in items] == [("lib:lib1", "library",
                                                                       "lib1")]  # fmt: skip


def test_served_items_are_recorded_and_terms_are_stable(env, docs):
    c = google()
    onboard(c)
    first = c.post(
        "/v1/onboarding/discover", json={"topics": ["economics", "sports"], "concepts": ["c_bond"]}
    ).json()
    again = c.post(
        "/v1/onboarding/discover", json={"topics": ["economics", "sports"], "concepts": ["c_bond"]}
    ).json()
    terms = {i["id"]: i["know"] and i["know"]["concept_id"] for i in first["items"]}
    assert terms == {i["id"]: i["know"] and i["know"]["concept_id"] for i in again["items"]}
    # c_bond was resolved and sent: never offered; c_inflation goes to one item only
    assert [t for t in terms.values() if t] == ["c_inflation"]
    served = docs.docs["users/g1/rec_signals/default"]["served"]
    assert set(terms) <= set(served) and {v["relation"] for v in served.values()} == {"feed"}


# ---------------------------------------------------------------- pick, know, finish


def _discover(c: TestClient, topics=("economics", "sports")) -> list[dict]:
    return c.post("/v1/onboarding/discover", json={"topics": list(topics)}).json()["items"]


def test_two_not_for_me_move_a_topic_behind_and_survive_edit(env, docs):
    c = google()
    onboard(c, ("economics", "sports"))
    items = _discover(c)
    sports = [i for i in items if i["topic"] == "sports"]
    for item in sports[:2]:
        resp = c.post("/v1/onboarding/pick", json={"item_id": item["id"], "liked": False})
        assert resp.status_code == 200
    assert docs.docs["users/g1/domains/sports"]["interest"] == pytest.approx(0.7)
    interest = {d: docs.docs[f"users/g1/domains/{d}"]["interest"] for d in ("economics", "sports")}
    assert reader_topics(interest) == ["economics", "sports"]
    onboard(c, ("sports", "economics"))  # Edit → Continue: picks re-applied
    assert docs.docs["users/g1/domains/sports"]["interest"] == pytest.approx(0.7)
    seen = docs.docs["users/g1/rec_signals/default"]["seen"]
    assert all(seen[i["id"]] == "dismissed" for i in sports[:2])


def test_pick_guards(env, monkeypatch):
    c = google()
    onboard(c)
    items = _discover(c)
    assert (
        c.post("/v1/onboarding/pick", json={"item_id": "feed:nope", "liked": True}).status_code
        == 404
    )
    first = {"item_id": items[0]["id"], "liked": True}
    assert c.post("/v1/onboarding/pick", json=first).status_code == 200
    assert c.post("/v1/onboarding/pick", json=first).status_code == 409
    monkeypatch.setattr(onboarding, "MAX_PICKS", 1)
    second = {"item_id": items[1]["id"], "liked": True}
    assert c.post("/v1/onboarding/pick", json=second).json() == {"error": "too_many_answers"}
    after = _discover(c)
    assert after[0]["liked"] is True  # resume shows the answer


def test_know_offered_only_once_and_same_as_calibration(env, docs):
    c = google()
    onboard(c)
    items = _discover(c)
    term = next(i["know"] for i in items if i["know"])
    assert c.post("/v1/onboarding/know",
                  json={"concept_id": "c_ma", "known": True}).status_code == 404  # fmt: skip
    theta0 = docs.docs["users/g1/domains/economics"].get("theta", 0.0)
    assert (
        c.post(
            "/v1/onboarding/know", json={"concept_id": term["concept_id"], "known": False}
        ).status_code
        == 200
    )
    assert (
        c.post(
            "/v1/onboarding/know", json={"concept_id": term["concept_id"], "known": True}
        ).status_code
        == 409
    )
    concept = GRAPH.get(term["concept_id"])
    stored = docs.docs[f"users/g1/knows/{concept.id}"]
    expected = onboarding.apply_answer(concept, None, theta0, "none", datetime.now(UTC))
    assert stored["band"] == expected.edge.band
    assert stored["alpha"] == pytest.approx(expected.edge.alpha)
    assert docs.docs["users/g1/domains/economics"]["theta"] == pytest.approx(expected.theta)
    assert model.band_of(model.p_know(expected.edge)) == stored["band"]


def test_finish_clears_the_lists_and_refuses_more(env, docs):
    c = google()
    onboard(c)
    resumed = c.get("/v1/me/profile").json()["onboarding"]
    assert resumed["step"] == "discover" and resumed["field"] == "software"
    assert resumed["interests"] == ["economics", "sports"]
    items = _discover(c)
    c.post("/v1/onboarding/pick", json={"item_id": items[0]["id"], "liked": True})
    assert c.post("/v1/onboarding/finish").json() == {"done": True}
    user = docs.docs["users/g1"]
    assert user["onboarding_done"] is True
    assert user["onboarding_offered"] == {} and user["onboarding_picks"] == {}
    assert c.get("/v1/me/profile").json()["onboarding"]["step"] == "done"
    assert c.post("/v1/onboarding/discover", json={"topics": ["law"]}).status_code == 409
    term = {"concept_id": "c_inflation", "known": True}
    assert c.post("/v1/onboarding/know", json=term).json() == {"error": "onboarding_done"}


def test_finish_needs_screen_1_saved(env):
    c = google()
    assert c.post("/v1/onboarding/finish").status_code == 409
    onboard(c)
    assert c.post("/v1/onboarding/finish").status_code == 200


def test_every_new_route_needs_consent_and_a_google_reader(env):
    demo = TestClient(app, headers=auth("demo", anonymous=True))
    fresh = google("fresh", consent=False)
    calls = [("/v1/onboarding/discover", {"topics": ["law"]}),
             ("/v1/onboarding/pick", {"item_id": "x", "liked": True}),
             ("/v1/onboarding/know", {"concept_id": "c_bond", "known": True}),
             ("/v1/onboarding/finish", None)]  # fmt: skip
    for path, body in calls:
        assert demo.post(path, json=body).status_code == 403
        assert fresh.post(path, json=body).status_code == 409


def test_new_counters_are_covered_by_export_and_delete(env, docs):
    assert {"onboarding_resolve_counts", "onboarding_discover_counts"} <= set(USER_SUBCOLLECTIONS)
    c = google()
    onboard(c)
    c.post("/v1/onboarding/resolve", json={"text": "F1"})
    _discover(c)
    exported = c.get("/v1/me/export").json()
    assert exported["onboarding_resolve_counts"] and exported["onboarding_discover_counts"]
    assert exported["user"]["onboarding_offered"]
    assert c.delete("/v1/me").status_code == 204
    assert not [k for k in docs.docs if k.startswith("users/g1")]


def test_consent_v1_stays_valid():
    c = TestClient(app, headers=auth("v1reader"))
    assert c.post("/v1/me/consent", json={"version": "consent-v1"}).status_code == 200
    assert c.post("/v1/me/consent", json={"version": "consent-v9"}).status_code == 422
