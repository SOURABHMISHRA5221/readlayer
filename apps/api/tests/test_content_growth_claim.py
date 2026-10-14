"""M9 G4: one grower per stored page across instances; a late finish never overwrites another."""

from datetime import UTC, datetime, timedelta

from app.store.content_repo import InMemoryContentStore
from tests.test_growth_reopen import page
from tests.test_growth_wiring import _demands

NOW = datetime(2026, 10, 15, 6, 0, tzinfo=UTC)
UNTIL = NOW + timedelta(seconds=60)


async def test_claim_absent_claimed_busy_and_expired():
    store = InMemoryContentStore()
    assert await store.claim_growth("c1", NOW, UNTIL) == ("absent", None)
    await store.put(page(grow_pending=True))
    status, token = await store.claim_growth("c1", NOW, UNTIL)
    assert status == "claimed" and token
    doc = await store.get("c1")
    assert doc.grow_pending is True  # a dead grower leaves the page pending
    assert await store.claim_growth("c1", NOW + timedelta(seconds=30), UNTIL) == ("busy", None)
    later = UNTIL + timedelta(seconds=1)
    status, again = await store.claim_growth("c1", later, later + timedelta(seconds=60))
    assert status == "claimed" and again != token


async def test_finish_writes_growth_fields_only_while_the_claim_is_ours():
    store = InMemoryContentStore()
    before = page(grow_pending=True)
    await store.put(before)
    _, token = await store.claim_growth("c1", NOW, UNTIL)
    linked = [d.model_copy(update={"target_id": "c_x", "grown": True}) for d in before.demands]
    assert await store.finish_growth("c1", "not-ours", linked, [], False, ["x"]) is False
    assert (await store.get("c1")).demands == before.demands
    assert await store.finish_growth("c1", token, linked, [], False, ["false nine"]) is True
    after = await store.get("c1")
    assert after.demands == linked and after.grow_pending is False
    assert after.grow_tried == ["false nine"]
    assert after.grow_token is None and after.growing_until is None
    assert after.paragraphs == before.paragraphs and after.title == before.title
    assert await store.finish_growth("c1", token, _demands(), [], True, []) is False  # once only


async def test_finish_without_demands_keeps_them_and_releases_the_claim():
    store = InMemoryContentStore()
    before = page(grow_pending=True)
    await store.put(before)
    _, token = await store.claim_growth("c1", NOW, UNTIL)
    assert await store.finish_growth("c1", token, None, [], True, []) is True
    after = await store.get("c1")
    assert after.demands == before.demands and after.grow_pending is True
    assert (await store.claim_growth("c1", NOW, UNTIL))[0] == "claimed"
