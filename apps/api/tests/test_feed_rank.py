"""For you feed ranking (M7.5 §A.5): matching, relevance, readiness, goals, quotas."""

from datetime import UTC, datetime, timedelta

from app.graph.graph import ConceptGraph
from app.graph.models import Concept, ConceptGraphFile
from app.reader.state import ReaderState
from app.recs import feed_rank as fr
from app.recs.models import WebResult
from app.recs.rank import FormatPrior

NOW = datetime(2026, 10, 11, tzinfo=UTC)


def concept(cid, label, domain, b=1.5, aliases=()):
    return Concept(id=cid, label=label, domain=domain, definition=f"{label}.",
                   aliases=list(aliases), base_difficulty=b, embedding=[1.0, 0.0])  # fmt: skip


GRAPH = ConceptGraph(ConceptGraphFile(version="t", concepts=[
    concept("c_offside", "Offside", "sports"),
    concept("c_penalty_kick", "Penalty kick", "sports", aliases=["penalty"]),
    concept("c_var", "Video assistant referee", "sports", aliases=["VAR"]),
    concept("c_insulin_resistance", "Insulin resistance", "health"),
    concept("c_inflation", "Inflation", "economics", b=-2.0),
]))  # fmt: skip


def result(title, fmt="article", snippet="", url=None, published=None):
    return WebResult(url=url or f"https://x.test/{abs(hash(title))}", title=title, source="x.test",
                     format=fmt, snippet=snippet, published_at=published)  # fmt: skip


def reader(**kw):
    prior = FormatPrior({"article": 0.5, "video": 0.5, "podcast": 0.5})
    interest = kw.pop("interest", {"sports": 1.0})
    return fr.FeedReader(state=ReaderState(), interest=interest, prior=prior, **kw)


def test_named_concepts_prefers_the_longest_match_and_aliases():
    text = "VAR overturned the penalty kick after an offside call"
    got = fr.named_concepts(GRAPH, text, "sports")
    assert [c.id for c in got] == ["c_var", "c_penalty_kick", "c_offside"]


def test_relevance_by_topic_word_or_a_concept_of_that_domain():
    no_word = result("West Ham denied as VAR missing in the Championship")
    assert fr.is_relevant(no_word, "sports", fr.named_concepts(GRAPH, no_word.title, "sports"))
    assert fr.is_relevant(result("Sports minister resigns"), "sports", ())
    off = result("Inflation eases in September")
    assert not fr.is_relevant(off, "sports", fr.named_concepts(GRAPH, off.title, "sports"))
    assert fr.is_relevant(
        result("Tech News This Week: Muse takes on small business"), "technology", ()
    )
    assert fr.is_relevant(result("OpenAI ships a new AI model"), "technology", ())
    assert fr.is_relevant(result("US economy adds 200,000 jobs"), "economics", ())
    assert not fr.is_relevant(
        result("Detached house prices"), "technology", ()
    )  # no "tech" inside words
    assert not fr.is_relevant(result("Paint the town"), "technology", ())


def test_article_dates_filter_at_fetch_time_only():
    old = result("x", published=(NOW - timedelta(days=20)).isoformat())
    rfc = result("x", published="Fri, 09 Oct 2026 10:00:00 GMT")
    assert not fr.recent_enough(old, NOW) and fr.recent_enough(rfc, NOW)
    assert fr.recent_enough(result("x", fmt="video", published="2020-01-01"), NOW)
    assert fr.recent_enough(result("undated"), NOW)


def test_feed_pages_are_single_articles_and_single_shows():
    articles = ["https://www.nytimes.com/2026/10/08/world/europe/united-nations-technology-warning.html",
                "https://www.reuters.com/business/us-consumer-sentiment-deteriorates-further",
                "https://www.bbc.com/news/articles/c8dn03216z3t"]  # fmt: skip
    hubs = ["https://techxplore.com", "https://www.pcmag.com/news",
            "https://www.aljazeera.com/tag/technology", "https://thehill.com/policy/technology",
            "https://www.bbc.com/news/topics/c8dn03216z3t",
            "https://www.merriam-webster.com/thesaurus/technology"]  # fmt: skip
    assert all(fr.looks_like_article(u) for u in articles)
    assert not any(fr.looks_like_article(u) for u in hubs)
    assert fr.is_listing_page("https://podcasts.apple.com/in/charts/1318")
    assert fr.is_listing_page("https://podcasts.apple.com/us/genre/1318")
    assert not fr.is_listing_page("https://open.spotify.com/show/4ln6H9peIXhq19yv3CdOvE")
    assert not fr.is_feed_page(result("p", fmt="podcast", url="https://www.podbean.com"))
    assert fr.is_feed_page(result("p", fmt="podcast", url="https://fordhamgsb.podbean.com"))
    assert fr.is_feed_page(result("v", fmt="video", url="https://www.youtube.com/watch?v=x"))
    assert not fr.is_feed_page(result("t", url="https://www.pcmag.com/news"))
    assert not fr.is_feed_page(result("എംബാപ്പെ റയൽ മാഡ്രിഡ് വിടുമോ? ലിവർപൂൾ", fmt="video"))
    assert fr.is_feed_page(result("Mbappé’s Real Madrid exit, explained", fmt="video"))


def test_readiness_curve():
    assert fr.readiness(0) == fr.NOTHING_NEW
    assert fr.readiness(1) == fr.readiness(4) == 1.0
    assert fr.readiness(6) == round(0.8**2, 10) or abs(fr.readiness(6) - 0.64) < 1e-9


def test_rank_counts_new_ideas_boosts_goals_and_explains_why():
    known_only = fr.FeedCandidate(
        result("Inflation news"), "sports", fr.named_concepts(GRAPH, "Inflation", "economics")
    )
    fresh = fr.FeedCandidate(result("Offside and VAR"), "sports",
                             fr.named_concepts(GRAPH, "Offside and VAR", "sports"))  # fmt: skip
    goal = fr.FeedCandidate(result("Insulin resistance explained"), "sports",
                            fr.named_concepts(GRAPH, "Insulin resistance", "health"))  # fmt: skip
    goals = {"c_insulin_resistance": "Insulin resistance"}
    out = fr.rank([known_only, fresh, goal], reader(goal_targets=goals), NOW, GRAPH)
    ranked = {r.candidate.result.title: r for r in out}
    assert ranked["Inflation news"].new_concepts == ()  # b = −2: known at θ 0
    assert ranked["Offside and VAR"].new_concepts == ("Offside", "Video assistant referee")
    assert ranked["Offside and VAR"].why == "Sports · 2 ideas new to you"
    g = ranked["Insulin resistance explained"]
    assert g.goal_label == "Insulin resistance" and "helps your goal: Insulin resistance" in g.why
    plain = fr.rank([goal], reader(), NOW, GRAPH)[0]
    assert (
        g.score == round(plain.score * fr.GOAL_BOOST, 4) or abs(g.score - plain.score * 1.3) < 1e-3
    )
    assert ranked["Offside and VAR"].score > ranked["Inflation news"].score


def test_select_applies_format_quotas_per_topic_and_the_cap():
    cands = [fr.FeedCandidate(result(f"Offside {i}", fmt, url=f"https://x.test/{t}/{fmt}/{i}"), t,
                              fr.named_concepts(GRAPH, "Offside", "sports"))
             for t in ("sports", "health") for fmt in ("article", "video", "podcast")
             for i in range(5)]  # fmt: skip
    picked = fr.select(fr.rank(cands, reader(interest={"sports": 1.0, "health": 0.5}), NOW, GRAPH),
                       ["sports", "health"])  # fmt: skip
    for t in ("sports", "health"):
        mine = [p.candidate.result.format for p in picked if p.candidate.topic == t]
        assert (
            mine.count("article") == 3 and mine.count("video") == 2 and mine.count("podcast") == 1
        )
    assert len(picked) == 12 <= fr.MAX_ITEMS
    assert len({p.candidate.result.url for p in picked}) == 12


# Live shapes (decision 64): one plain word must not name a concept in another sense.
LIVE = ConceptGraph(ConceptGraphFile(version="t", concepts=[
    concept("c_stock_variable", "Stock variable", "economics", aliases=["stocks", "stock terms"]),
    concept("c_stock_market", "Stock market update", "finance", aliases=["Stock market"]),
    concept("c_futures", "Futures contract", "finance", aliases=["futures"]),
    concept("c_basis", "Basis (finance)", "finance"),
    concept("c_rbi", "RBI", "policy", aliases=["Reserve Bank of India", "RBI’s"]),
    concept("c_repo", "Repo rate", "finance"),
    concept("c_gdp", "GDP", "economics"),
    concept("c_ma", "M&A", "business"),
    concept("c_ebitdar", "EBITDAR", "finance"),
    concept("c_cafe", "CAFE", "policy"),
    concept("c_inflation", "Inflation", "economics"),
    concept("c_spread", "Spread", "finance"),
    concept("c_take_a_touch", "Take a touch", "sports", aliases=["to"]),
]))  # fmt: skip


def named(text, topic):
    return [c.id for c in fr.named_concepts(LIVE, text, topic)]


def test_single_lowercase_aliases_never_count_in_free_text():
    assert named("Chip stocks tumble", "finance") == []
    assert named("Stock market today", "finance") == ["c_stock_market"]
    assert named("Gadgets of the future", "technology") == []
    assert named("Futures contract prices", "finance") == ["c_futures"]
    assert named("on a working arrangement basis", "policy") == []  # a parenthetical label
    assert named("Back to work", "sports") == []  # the stopword alias is gone


def test_caps_names_need_caps_in_the_text_and_cross_domains():
    assert named("RBI raises the repo rate", "economics") == ["c_rbi", "c_repo"]
    assert named("Rates at the RBI", "economics") == ["c_rbi"]
    assert named("rbi notes", "economics") == []
    assert named("The RBI’s move", "economics") == ["c_rbi"]  # a possessive keeps the caps
    assert named("M&A deals and GDP growth", "technology") == ["c_ma", "c_gdp"]
    assert named("EBITDAR margin", "finance") == ["c_ebitdar"]
    assert named("ebitdar margin", "finance") == []
    assert named("Cafe owners", "policy") == []


def test_plain_single_labels_count_in_their_own_domain_or_the_business_group():
    assert named("Inflation rises", "economics") == ["c_inflation"]
    assert named("Inflation rises", "sports") == []
    assert named("Virus spread slows", "health") == []
    assert named("Spread widens", "finance") == ["c_spread"]
    assert named("Spread widens", "policy") == ["c_spread"]  # policy is in the business group


def test_latin_titles_allow_accents_symbols_and_one_stray_letter():
    assert not fr.is_latin_title(
        "ഈ റാലി സൂചനയോ| Political Analysis|Debate Malayalam| NEWS INDIA MALAYALAM POINT"
    )
    assert fr.is_latin_title("Müller's café reopens")
    assert fr.is_latin_title("ASUS laptops ₹21,000 off 🔴 live")
    assert fr.is_latin_title("The μ problem in markets")
