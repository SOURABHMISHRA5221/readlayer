"""Readiness on For you (decision 60, plan docs/plans/readiness.md): from the reader's own map."""

from app.graph.graph import ConceptGraph
from app.graph.models import ConceptGraphFile
from app.recs import feed_rank as fr
from app.recs.feed_router import _out
from tests.test_feed_rank import GRAPH, NOW, concept, reader, result

# b: base difficulty. At θ 0 a concept with b ≥ 0 is new (p < 0.5), with b < 0 known.
PRE = ConceptGraph(ConceptGraphFile(version="t", concepts=[
    concept("c_money", "Money", "economics", b=-2.0),                  # known
    concept("c_interest", "Interest rate", "economics", b=0.5),        # new, basic
    concept("c_bond", "Bond", "economics", b=1.0),                     # new
    concept("c_yield", "Bond yield", "economics", b=1.5),              # new
    concept("c_curve", "Yield curve", "economics", b=1.8),             # new
    concept("c_inverted", "Inverted yield curve", "economics", b=2.0),  # new
    concept("c_cash", "Cash", "economics", b=1.0),                     # new, no prerequisites
]))  # fmt: skip
PREREQS = {
    "c_bond": ["c_money", "c_interest"],
    "c_yield": ["c_bond", "c_interest"],
    "c_curve": ["c_yield", "c_interest", "c_missing"],
    "c_inverted": ["c_curve"],
}
PRE = ConceptGraph(ConceptGraphFile(version="t", concepts=[
    c.model_copy(update={"prerequisites": PREREQS.get(c.id, [])}) for c in PRE.concepts
]))  # fmt: skip


def item(text, topic="economics"):
    return fr.FeedCandidate(result(text, url=f"https://x.test/{abs(hash(text))}"), topic,
                            fr.named_concepts(PRE, text, topic))  # fmt: skip


def ranked(text, **kw):
    return fr.rank([item(text)], reader(interest={"economics": 1.0}, **kw), NOW, PRE)[0]


def test_new_ideas_whose_groundwork_is_known_are_ready():
    r = ranked("Cash")  # new, no prerequisites in the graph: ready (the map shows no ring)
    assert r.readiness == "ready" and r.read_first == ()


def test_a_new_prerequisite_is_listed_most_basic_first_and_capped():
    r = ranked("Inverted yield curve")
    assert r.readiness == "stretch"
    assert r.read_first == ("Yield curve",)
    r = ranked("Yield curve")  # prerequisites Bond yield and Interest rate are both new
    assert r.read_first == ("Interest rate", "Bond yield")  # most basic (b) first, at most 2
    assert len(fr.read_first(list(item("Yield curve").concepts), frozenset(), PRE,
                             reader().state, NOW)) <= fr.READ_FIRST_MAX  # fmt: skip


def test_a_prerequisite_the_item_names_itself_is_not_listed_but_still_counts():
    r = ranked("Bond and Interest rate")
    assert r.new_concepts == ("Bond", "Interest rate")
    assert r.read_first == () and r.readiness == "ready"


def test_a_known_prerequisite_is_never_listed_and_a_missing_id_is_harmless():
    assert ranked("Bond").read_first == ("Interest rate",)  # Money is known
    assert "c_missing" in PREREQS["c_curve"] and ranked("Yield curve").readiness == "stretch"


def test_levels():
    assert fr.readiness_level(0, 0, ()) is None  # names nothing: no line, we know nothing
    assert fr.readiness_level(2, 0, ()) == "familiar"
    assert fr.readiness_level(2, 1, ()) == fr.readiness_level(5, 4, ()) == "ready"
    assert fr.readiness_level(6, 5, ()) == "stretch"  # many new ideas at once
    assert fr.readiness_level(1, 1, ("Bond",)) == "stretch"


def test_an_item_that_names_no_concept_has_no_level():
    r = fr.rank([fr.FeedCandidate(result("Markets today"), "economics", ())],
                reader(interest={"economics": 1.0}), NOW, PRE)[0]  # fmt: skip
    assert r.readiness is None and r.read_first == ()


def test_known_ideas_only_are_mostly_familiar():
    assert ranked("Money").readiness == "familiar"


def test_ranking_scores_are_unchanged():
    c = fr.FeedCandidate(result("Offside and VAR", url="https://x.test/a"), "sports",
                         fr.named_concepts(GRAPH, "Offside and VAR", "sports"))  # fmt: skip
    assert fr.rank([c], reader(), NOW, GRAPH)[0].score == 0.85  # pinned before the change


def test_select_and_the_route_model_carry_both_fields():
    picked = fr.select(fr.rank([item("Inverted yield curve")], reader(interest={"economics": 1.0}),
                               NOW, PRE), ["economics"])  # fmt: skip
    out = _out(picked[0])
    assert out.readiness == "stretch" and out.read_first == ["Yield curve"]
    none = _out(fr.rank([fr.FeedCandidate(result("Markets"), "economics", ())],
                        reader(interest={"economics": 1.0}), NOW, PRE)[0])  # fmt: skip
    assert none.readiness is None and none.read_first == []


# ---------------------------------------------------------------- decision 65: stored articles

from app.ingest.models import Anchor, ContentDoc, Demand, StoredParagraph  # noqa: E402
from app.ingest.urls import url_hash  # noqa: E402

ARTICLE_URL = "https://www.bbc.co.uk/news/articles/c5djvyde0y1jo"


def demand(target, salience, i):
    return Demand(id=f"d{i}", paragraph_id="p0", type="concept", label=target, target_id=target,
                  anchor=Anchor(exact=target, prefix="", suffix="", start=0, end=1),
                  salience=salience, explained_in_text=False, zipf=3.0)  # fmt: skip


def stored(url, targets, source="fetch"):
    return ContentDoc(
        content_id=url_hash(url), url=url, final_url=url, title="t", site="BBC", source=source,
        fetched_at="now", paragraphs=[StoredParagraph(id="p0", text="x", structure=0.0)],
        demands=[demand(t, s, i) for i, (t, s) in enumerate(targets)], demands_dropped=0,
        llm_calls=[],
    )  # fmt: skip


def stored_row(targets, fmt="article", url=ARTICLE_URL, title="How a toy gets to a retailer",
               source="fetch", doc_url=None):  # fmt: skip
    cand = fr.FeedCandidate(result(title, fmt=fmt, url=url), "economics",
                            fr.named_concepts(PRE, title, "economics"))  # fmt: skip
    docs = {d.content_id: d for d in [stored(doc_url or url, targets, source)]}
    (attached,) = fr.attach_ideas([cand], docs, PRE)
    return cand, attached


def ranked_one(c):
    return fr.rank([c], reader(interest={"economics": 1.0}), NOW, PRE)[0]


def test_a_stored_article_shows_its_key_ideas_and_keeps_the_title_score():
    targets = [("c_cash", 0.9), ("c_money", 0.8), ("c_bond", 0.7), ("c_cash", 0.95),
               ("c_gone", 0.99), ("c_yield", 0.2), ("c_curve", 0.1)]  # fmt: skip
    plain, c = stored_row(targets)
    assert [x.id for x in c.ideas] == ["c_cash", "c_money", "c_bond", "c_yield"]  # top 4, once
    r, title_only = ranked_one(c), ranked_one(plain)
    assert r.readiness_basis == "article" and title_only.readiness_basis == "title"
    assert r.score == title_only.score
    assert r.new_concepts == ("Cash", "Bond", "Bond yield") and "3 ideas new to you" in r.why
    assert r.readiness == "stretch" and r.read_first == ("Interest rate",)


def test_a_prerequisite_the_article_links_is_never_read_first():
    targets = [("c_bond", 0.9), ("c_money", 0.8), ("c_cash", 0.7), ("c_yield", 0.6),
               ("c_curve", 0.5), ("c_interest", 0.1)]  # Interest rate: its 6th idea  # fmt: skip
    _, c = stored_row(targets)
    assert "c_interest" not in {x.id for x in c.ideas}
    assert "Interest rate" not in ranked_one(c).read_first


def test_videos_unstored_private_and_unlinked_articles_keep_the_title_rule():
    targets = [("c_cash", 0.9)]
    for kw in ({"fmt": "video"}, {"source": "user_ingested"}, {"source": "extension"},
               {"doc_url": "https://www.bbc.co.uk/news/articles/other"}):  # fmt: skip
        _, c = stored_row(targets, **kw)
        assert c.ideas is None and ranked_one(c).readiness_basis == "title"
    _, c = stored_row([("c_gone", 0.9)])  # no linked demand in the graph
    assert c.ideas is None
    for ideas in (None, ()):
        named = fr.named_concepts(PRE, "Money", "economics")
        plain = fr.FeedCandidate(result("Money", url=ARTICLE_URL), "economics", named, ideas=ideas)
        assert ranked_one(plain).readiness_basis == "title"


def test_a_tracking_query_still_finds_the_stored_article():
    _, c = stored_row([("c_cash", 0.9)], url=f"{ARTICLE_URL}?utm_source=rss&utm_medium=feed",
                      doc_url=ARTICLE_URL)  # fmt: skip
    assert c.ideas is not None and [x.id for x in c.ideas] == ["c_cash"]
