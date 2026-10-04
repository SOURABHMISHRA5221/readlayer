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


def test_select_caps_per_format_and_total():
    cands = [cand(f"a{i}", "article", relevance=1 - i / 100) for i in range(5)]
    cands += [cand(f"v{i}", "video", relevance=0.5) for i in range(5)]
    cands += [cand(f"p{i}", "podcast", relevance=0.4) for i in range(5)]
    chosen = rank.select(cands, ReaderSignals(), NEUTRAL, NOW)
    formats = [c.format for c, _ in chosen]
    assert len(chosen) == 6 and all(formats.count(f) == 2 for f in ("article", "video", "podcast"))
    assert [c.id for c, _ in chosen][:2] == ["a0", "a1"]


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
    assert top == {"newcomer": "vid", "trader": "art", "policy_student": "art"}


def test_select_mixes_library_and_web_when_both_exist():
    lib = [cand(f"l{i}", "article", relevance=0.3) for i in range(3)]
    web = [Candidate(f"w{i}", "explainer", "article", 0.9, None, None, "web") for i in range(3)]
    chosen = rank.select(lib + web, ReaderSignals(), NEUTRAL, NOW)
    assert {c.kind for c, _ in chosen} == {"library", "web"}
    assert [c.id for c, _ in chosen] == ["w0", "l0"]  # 2 articles max, still ordered by score
