"""Guards of the demo pre-ingest (plan docs/plans/oct16.md S6): offline, made-up counters."""

import asyncio

from scripts.preingest_feed import GROWTH_MIN_LEFT, ordered_urls, run, url_cap


def test_the_run_leaves_ten_shared_ingests_for_people_and_never_exceeds_twenty():
    assert url_cap(used=0, shared_cap=30) == 20
    assert url_cap(used=15, shared_cap=30) == 5
    assert url_cap(used=20, shared_cap=30) == 0
    assert url_cap(used=28, shared_cap=30) == 0


def test_newcomer_and_trader_rows_first_and_a_shared_url_once():
    rows = {"policy_student": ["p1", "shared"], "trader": ["t1", "shared"], "newcomer": ["n1"]}
    assert ordered_urls(rows) == ["n1", "t1", "shared", "p1"]


def posting(growth_left: list[int]):
    posted: list[str] = []

    async def left() -> int:
        return growth_left.pop(0) if growth_left else 150

    async def post(url: str) -> str:
        posted.append(url)
        return "ready"

    return posted, left, post


def test_nothing_is_posted_when_the_cap_is_zero():
    posted, left, post = posting([])
    assert asyncio.run(run(["a", "b"], 0, left, post)) == []
    assert posted == []


def test_the_run_stops_before_the_next_url_when_growth_slots_run_low():
    posted, left, post = posting([150, GROWTH_MIN_LEFT - 1])
    done = asyncio.run(run(["a", "b", "c"], 20, left, post))
    assert posted == ["a"]
    assert done == [("a", "ready"), ("b", f"stopped: {GROWTH_MIN_LEFT - 1} growth slots left")]
