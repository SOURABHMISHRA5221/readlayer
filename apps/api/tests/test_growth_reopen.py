"""M9 part 1, pure parts: tried labels are not picked again, and which stored pages need growth."""

import pytest

from app.graph import growth
from app.ingest.models import ContentDoc, LLMCall, Media
from tests.test_growth import TEXT, demand


def page(source="extension", demands=None, calls=(), grow_pending=None, tried=(), media=None):
    return ContentDoc(
        content_id="c1", url="https://x.example/a", final_url="https://x.example/a", title="T",
        site="x.example", source=source, fetched_at="2026-10-13T00:00:00+00:00", paragraphs=[],
        demands=demands if demands is not None else [demand("d1", "False nine"),
                                                     demand("d2", "Offside")],
        demands_dropped=0, llm_calls=[call(t) for t in calls], media=media,
        grow_pending=grow_pending, grow_tried=list(tried),
    )  # fmt: skip


def call(task):
    return LLMCall(task=task, model="m", prompt_version="v", tokens_in=1, tokens_out=1,
                   cost_usd=0.0, fell_back=False)  # fmt: skip


def test_pick_skips_labels_already_tried():
    ds = [
        demand("d1", "False nine", 0.9),
        demand("d2", "Offside", 0.7),
        demand("d3", "Pressing", 0.5),
    ]
    got = growth.pick(ds, {"p0": TEXT}, limit=5, exclude=frozenset({"false nine"}))
    assert [p.label for p in got] == ["Offside", "Pressing"]
    assert growth.untried_count(ds, frozenset({"false nine", "offside"}), limit=5) == 1


@pytest.mark.parametrize(
    ("doc", "heldout", "expected"),
    [
        (page(grow_pending=True), False, True),
        (page(grow_pending=False), False, False),
        (page(source="user_ingested", grow_pending=True), False, True),
        # never: not the reader's own page, or held out, whatever the flag says (G1)
        (page(source="fetch", grow_pending=True), False, False),
        (page(grow_pending=True), True, False),
        # nothing left to try
        (page(grow_pending=True, tried=("false nine", "offside")), False, False),
        (page(grow_pending=True, demands=[demand("d1", "Goal", target="c_goal")]), False, False),
        # old pages (no flag): extension pages never grown, not recordings (G2)
        (page(), False, True),
        (page(calls=("extract_demands",)), False, True),
        (page(calls=("concept_define",)), False, False),
        (page(calls=("link_merge",)), False, False),
        (page(source="user_ingested"), False, False),
        (page(media=Media(kind="youtube", video_id="R8VBRCs2jTU", duration_s=494)), False, False),
    ],
)
def test_needs_growth(doc, heldout, expected):
    assert growth.needs_growth(doc, heldout=heldout) is expected


def test_a_stored_page_reads_without_the_new_fields():
    doc = ContentDoc.model_validate(page().model_dump(exclude={"grow_pending", "grow_tried"}))
    assert doc.grow_pending is None and doc.grow_tried == []


async def test_the_reserver_takes_what_growth_will_try_within_the_caps(docs):
    from app.auth import Caller
    from app.config import Settings
    from app.ingest import quota
    from app.store.spend_repo import today_utc

    s = Settings(_env_file=None, growth_enabled=True, growth_per_article=5, growth_per_uid_day=8,
                 growth_per_day=300, anon_growth_daily_cap=150)  # fmt: skip
    reserve = quota.growth_reserver(Caller("g1", False), s)
    assert await reserve(9) == 5  # never more than one article's worth
    assert await reserve(0) == 0
    assert await reserve(5) == 3  # the reader's cap
    assert docs.docs[f"users/g1/growth_counts/{today_utc()}"]["count"] == 8
    anon = quota.growth_reserver(Caller("a1", True), s)
    assert await anon(2) == 2
    assert docs.docs[f"ops/growth/anon_days/{today_utc()}"]["count"] == 2
    assert (
        quota.growth_reserver(Caller("g1", False), Settings(_env_file=None, growth_enabled=False))
        is None
    )
