from datetime import UTC, datetime, timedelta

import pytest

from app.recs import rank
from app.recs.rank import Candidate, FormatPrior, FormatStats, ReaderSignals

NOW = datetime(2026, 10, 4, tzinfo=UTC)
NEUTRAL = FormatPrior({"article": 0.5, "video": 0.5, "podcast": 0.5})


def cand(cid, fmt="article", relation="primer", relevance=1.0, published=None, duration=None):
    return Candidate(cid, relation, fmt, relevance, published, duration)


def test_score_is_the_product_of_its_factors():
    c = cand("a", published=(NOW - timedelta(days=30)).isoformat(), relation="deeper")
    expected = (
        1.0
        * rank.RELATION_WEIGHT["deeper"]
        * rank.format_affinity("article", NEUTRAL, FormatStats())
        * rank.freshness(c.published_at, NOW)
        * 1.0
    )
    assert rank.score(c, ReaderSignals(), NEUTRAL, NOW) == pytest.approx(expected)
    assert rank.freshness(c.published_at, NOW) == pytest.approx(0.8)  # one half-life
    assert rank.freshness(None, NOW) == rank.UNDATED_FRESHNESS


def test_format_affinity_is_a_smoothed_rate():
    neutral = rank.format_affinity("video", NEUTRAL, FormatStats())
    assert neutral == pytest.approx(1.0)
    liked = rank.format_affinity("video", NEUTRAL, FormatStats(shown=3, clicks=3, completions=1))
    disliked = rank.format_affinity("video", NEUTRAL, FormatStats(shown=3, dismissals=3))
    assert disliked < neutral < liked <= 1.5
    # smoothing: one click moves it less than three
    one = rank.format_affinity("video", NEUTRAL, FormatStats(shown=1, clicks=1))
    assert neutral < one < liked


def test_explicit_preference_beats_persona_default():
    newcomer = rank.PERSONA_FORMAT_PRIORS["newcomer"]
    video = rank.format_affinity("video", newcomer, FormatStats())
    article = rank.format_affinity("article", newcomer, FormatStats())
    assert video > article
    assert rank.format_affinity(
        "article", newcomer, FormatStats(), "article"
    ) > rank.format_affinity("video", newcomer, FormatStats(), "article")


def test_article_length_preference():
    trader, policy = (
        rank.PERSONA_FORMAT_PRIORS["trader"],
        rank.PERSONA_FORMAT_PRIORS["policy_student"],
    )
    short, long_ = 180, 900
    assert rank.format_affinity(
        "article", trader, FormatStats(), None, short
    ) > rank.format_affinity("article", trader, FormatStats(), None, long_)
    assert rank.format_affinity(
        "article", policy, FormatStats(), None, long_
    ) > rank.format_affinity("article", policy, FormatStats(), None, short)


def test_dismissing_lowers_the_relation_weight_with_a_floor():
    assert rank.relation_weight("angle", 1) < rank.relation_weight("angle", 0)
    assert rank.relation_weight("angle", 50) == pytest.approx(
        rank.RELATION_WEIGHT["angle"] * rank.MIN_RELATION_FACTOR
    )


def test_not_seen():
    signals = ReaderSignals(
        seen={"a": "completed", "b": "dismissed", "c": "clicked"}, shown_counts={"d": 3}
    )
    assert [rank.not_seen(i, signals) for i in "abcde"] == [0.0, 0.0, 0.3, 0.8, 1.0]


def plenty():
    cands = [cand(f"a{i}", "article", relevance=1 - i / 100) for i in range(5)]
    cands += [cand(f"v{i}", "video", relevance=0.5) for i in range(5)]
    cands += [cand(f"p{i}", "podcast", relevance=0.4) for i in range(5)]
    return cands


def mix(chosen):
    formats = [c.format for c, _ in chosen]
    return {f: formats.count(f) for f in ("article", "video", "podcast")}


def test_preferred_format_gets_three_slots_then_two_then_one():
    chosen = rank.select(plenty(), ReaderSignals(), NEUTRAL, NOW)  # tie → article, video, podcast
    assert len(chosen) == 6 and mix(chosen) == {"article": 3, "video": 2, "podcast": 1}
    assert [c.id for c, _ in chosen][:3] == ["a0", "a1", "a2"]


def test_explicit_preference_and_affinity_set_the_order():
    podcast_first = rank.select(plenty(), ReaderSignals(), NEUTRAL, NOW, explicit="podcast")
    assert mix(podcast_first)["podcast"] == 3
    # an affinity order without an explicit choice: video liked, article disliked
    signals = ReaderSignals(
        formats={
            "video": FormatStats(shown=4, clicks=4),
            "article": FormatStats(shown=4, dismissals=4),
        }
    )
    assert rank.format_order(signals, NEUTRAL) == ["video", "podcast", "article"]
    assert mix(rank.select(plenty(), signals, NEUTRAL, NOW)) == {
        "video": 3,
        "podcast": 2,
        "article": 1,
    }


def test_short_formats_pass_their_slots_to_the_next_format():
    order = ["video", "article", "podcast"]
    assert rank.format_quotas(order, {"video": 1, "article": 9, "podcast": 9}) == {
        "video": 1,
        "article": 4,
        "podcast": 1,
    }
    assert rank.format_quotas(order, {"video": 9, "article": 0, "podcast": 9}) == {
        "video": 3,
        "article": 0,
        "podcast": 3,
    }
    # the last format's spare wraps round to the most preferred one
    assert rank.format_quotas(order, {"video": 9, "article": 9, "podcast": 0}) == {
        "video": 4,
        "article": 2,
        "podcast": 0,
    }
    assert rank.format_quotas(order, {"video": 1, "article": 1, "podcast": 0}) == {
        "video": 1,
        "article": 1,
        "podcast": 0,
    }


def test_select_skips_seen_and_duplicates_and_reorders_on_dismissal():
    cands = [
        cand("x", relation="angle", relevance=1.0),
        cand("x", relation="primer", relevance=0.5),
        cand("y", "video", relation="primer", relevance=0.8),
        cand("z", "podcast", relation="deeper", relevance=0.7),
    ]
    first = [c.id for c, _ in rank.select(cands, ReaderSignals(), NEUTRAL, NOW)]
    assert first == ["x", "y", "z"]
    signals = ReaderSignals(seen={"y": "dismissed"}, relation_dismissals={"angle": 3})
    after = rank.select(cands, signals, NEUTRAL, NOW)
    assert [(c.id, c.relation) for c, _ in after] == [("z", "deeper"), ("x", "primer")]


def test_persona_defaults_change_the_order():
    cands = [cand("art", "article", duration=200), cand("vid", "video")]
    top = {
        p: rank.select(cands, ReaderSignals(), prior, NOW)[0][0].id
        for p, prior in rank.PERSONA_FORMAT_PRIORS.items()
    }
    assert top == {"newcomer": "vid", "trader": "art", "policy_student": "art", "default": "art"}


def test_select_mixes_library_and_web_when_both_exist():
    lib = [cand("l0", "article", relevance=0.3)]
    web = [Candidate(f"w{i}", "explainer", "article", 0.9, None, None, "web") for i in range(4)]
    videos = [Candidate(f"v{i}", "explainer", "video", 0.8, None, None, "web") for i in range(3)]
    chosen = rank.select(lib + web + videos, ReaderSignals(), NEUTRAL, NOW)
    ids = [c.id for c, _ in chosen]
    # article 3 + the podcast slot passed on = 4; the library item replaces the weakest article
    assert mix(chosen) == {"article": 4, "video": 2, "podcast": 0}
    assert "l0" in ids and "w3" not in ids
    assert ids == ["w0", "w1", "w2", "v0", "v1", "l0"]  # still ordered by score


def test_feed_dismissals_never_touch_up_next_and_seen_maps_stay_bounded():
    from datetime import UTC, datetime, timedelta

    from app.recs.state import MAX_SERVED, RecSignalsDoc, Served, apply_event, remember

    doc = RecSignalsDoc()
    now = datetime(2026, 10, 11, tzinfo=UTC)
    remember(doc, {"feed:a": Served("article", "feed"), "lib:b": Served("article", "primer")}, now)
    assert apply_event(doc, "e1", "rec_dismissed", "feed:a")
    assert doc.relation_dismissals == {}  # Up next relation weights unchanged
    assert apply_event(doc, "e2", "rec_dismissed", "lib:b")
    assert doc.relation_dismissals == {"primer": 1}
    for i in range(MAX_SERVED + 50):
        remember(doc, {f"feed:{i}": Served("video", "feed")}, now + timedelta(seconds=i + 1))
        apply_event(doc, f"s{i}", "rec_shown", f"feed:{i}")
    assert len(doc.served) == MAX_SERVED
    assert set(doc.shown_counts) <= set(doc.served) and set(doc.seen) <= set(doc.served)


def test_one_per_format_keeps_the_best_of_each_in_format_order():
    """Decision 67 N1: the card's chips, at most one read / watch / listen."""
    from app.recs.rank import Candidate, one_per_format

    def c(i, fmt):
        return Candidate(i, "explainer", fmt, 1.0)

    chosen = [(c("v1", "video"), 0.9), (c("a1", "article"), 0.5), (c("v2", "video"), 0.95),
              (c("a2", "article"), 0.7)]  # fmt: skip
    picked = one_per_format(chosen)
    assert [(x.id, s) for x, s in picked] == [("a2", 0.7), ("v2", 0.95)]
    assert one_per_format([]) == []
