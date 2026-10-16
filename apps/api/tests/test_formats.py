"""Decision 68 F: read / watch / listen from onboarding shapes recommendations, the feed and
screen 2."""

from datetime import UTC, datetime

from app.recs import feed_rank as fr
from app.recs import rank
from app.recs.models import WebResult

NOW = datetime(2026, 10, 17, tzinfo=UTC)


def test_format_prior_and_who_gets_it():
    p = rank.format_prior(["video"])
    assert p.means == {"article": 0.4, "video": 0.75, "podcast": 0.4}
    assert rank.prior_for("trader", ["video"]) is rank.PERSONA_FORMAT_PRIORS["trader"]
    assert rank.prior_for("default", ["video"]).means["video"] == 0.75
    assert rank.prior_for("default", []) is rank.PERSONA_FORMAT_PRIORS["default"]


def test_chips_put_the_chosen_formats_first():
    def c(i, fmt):
        return rank.Candidate(i, "explainer", fmt, 1.0)

    chosen = [(c("a", "article"), 0.9), (c("v", "video"), 0.5), (c("p", "podcast"), 0.4)]
    assert [x.id for x, _ in rank.one_per_format(chosen, ["podcast"])] == ["p", "a", "v"]
    assert [x.id for x, _ in rank.one_per_format(chosen, ["video", "podcast"])] == ["v", "p", "a"]
    assert [x.id for x, _ in rank.one_per_format(chosen)] == ["a", "v", "p"]


def test_feed_quotas_follow_the_chosen_formats():
    assert fr.quotas_for([]) is fr.QUOTAS
    assert fr.quotas_for(["article", "video", "podcast"]) is fr.QUOTAS
    assert fr.quotas_for(["video"]) == {"article": 2, "video": 3, "podcast": 1}
    assert fr.quotas_for(["podcast", "article"]) == {"article": 3, "video": 1, "podcast": 2}


def cand(url, topic, fmt="article", day=1):
    res = WebResult(url=url, title="t", source="s", format=fmt, published_at=f"2026-10-{day:02d}")
    return fr.FeedCandidate(res, topic)


def test_screen_2_mix_minimums_and_chosen_first():
    sports = [cand(f"s{i}", "sports") for i in range(5)] + [cand("sv1", "sports", "video"),
              cand("sv2", "sports", "video"), cand("sp1", "sports", "podcast")]  # fmt: skip
    law = [cand(f"l{i}", "law") for i in range(5)] + [cand("lp1", "law", "podcast")]
    got = fr.onboarding_mix([sports, law], NOW, 6, formats=["video"])
    fmts = [c.result.format for c in got]
    assert len(got) == 6 and fmts.count("video") >= 2 and fmts.count("podcast") >= 1
    assert got[0].result.format == "video"  # chosen first within the first group
    only_read = fr.onboarding_mix([sports, law], NOW, 6, formats=["article"])
    of = [c.result.format for c in only_read]
    assert of.count("video") == 1 and of.count("podcast") == 1 and of.count("article") == 4


def test_screen_2_keeps_served_cards_in_place_when_videos_arrive_late():
    first = fr.onboarding_mix(
        [[cand("a1", "sports"), cand("a2", "sports")]], NOW, 3, formats=["video"]
    )
    served = [c.result.url for c in first]
    later = [[cand("v1", "sports", "video"), cand("v2", "sports", "video"),
              cand("a1", "sports"), cand("a2", "sports")]]  # fmt: skip
    again = fr.onboarding_mix(later, NOW, 3, formats=["video"], served=served)
    assert [c.result.url for c in again][: len(served)] == served
    assert {c.result.url for c in again} == {"a1", "a2", "v1"}


def test_screen_2_holds_slots_for_missing_formats_while_searches_run():
    """Harness R0: the first poll had only videos and podcasts; served cards then filled all 9
    and articles never got a card. While pending, unmet minimums keep their slots free."""
    early = [
        [cand(f"v{i}", "economics", "video") for i in range(8)]
        + [cand("p1", "economics", "podcast")]
    ]
    first = fr.onboarding_mix(early, NOW, 9, formats=["video"], pending=True)
    assert len(first) == 8 and not any(
        c.result.format == "article" for c in first
    )  # 1 kept for an article
    served = [c.result.url for c in first]
    late = [early[0] + [cand("a1", "economics")]]
    again = fr.onboarding_mix(late, NOW, 9, formats=["video"], served=served, pending=False)
    assert [c.result.url for c in again][:8] == served and again[8].result.url == "a1"
    done = fr.onboarding_mix(early, NOW, 9, formats=["video"], pending=False)
    assert len(done) == 9  # searches finished with no article: the slot is used


# Decision 69 G (Sourabh: screen 2 was "full read read read"): the chosen formats share the
# cards equally, every other format still gets one, and the chosen formats take turns.


def _plenty(topic):
    return ([cand(f"{topic}-a{i}", topic, "article", day=9 - i) for i in range(6)]
            + [cand(f"{topic}-p{i}", topic, "podcast", day=8 - i) for i in range(4)]
            + [cand(f"{topic}-v{i}", topic, "video", day=7 - i) for i in range(4)])  # fmt: skip


def test_screen_2_shares_cards_equally_between_the_chosen_formats():
    groups = [_plenty("sports"), _plenty("economics"), _plenty("business")]
    got = fr.onboarding_mix(groups, NOW, 9, formats=["article", "podcast"])
    fmts = [c.result.format for c in got]
    assert (fmts.count("article"), fmts.count("podcast"), fmts.count("video")) == (4, 4, 1)
    assert fmts[:8] == ["article", "podcast"] * 4  # they take turns; the other format comes last
    one = [c.result.format for c in fr.onboarding_mix(groups, NOW, 9, formats=["podcast"])]
    assert (one.count("podcast"), one.count("article"), one.count("video")) == (7, 1, 1)
    all_three = fr.onboarding_mix(groups, NOW, 9, formats=["article", "video", "podcast"])
    every = [c.result.format for c in all_three]
    assert (every.count("article"), every.count("video"), every.count("podcast")) == (3, 3, 3)
    articles = [c.topic for c in got if c.result.format == "article"][:3]
    assert len(set(articles)) == 3  # topics still interleave within a format


def test_a_short_chosen_format_is_made_up_by_the_other_chosen_one():
    groups = [[*(cand(f"a{i}", "law") for i in range(9)), cand("p1", "law", "podcast"),
               cand("v1", "law", "video")]]  # fmt: skip
    got = [
        c.result.format for c in fr.onboarding_mix(groups, NOW, 9, formats=["article", "podcast"])
    ]
    assert got.count("podcast") == 1 and got.count("video") == 1 and got.count("article") == 7
