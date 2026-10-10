"""Growth store and slot counters (M2.2 plan §C.3, §C.6)."""

from datetime import UTC, datetime, timedelta

from app.graph.models import Concept
from app.store.docstore import InMemoryDocStore
from app.store.growth_repo import GrowthRepo
from app.store.reader_repo import ReaderRepo


def _concept(cid: str = "c_offside") -> Concept:
    return Concept(id=cid, label="Offside", domain="sports", definition="A rule of football.",
                   base_difficulty=0.1, kind="method", embedding=[1.0, 0.0])  # fmt: skip


async def test_create_if_absent_never_overwrites_and_stamps_the_store_clock():
    store = InMemoryDocStore()
    repo = GrowthRepo(store)
    assert await repo.create_if_absent(_concept(), "cid1", {"concept_define": "v3"})
    other = _concept().model_copy(update={"definition": "Something else entirely."})
    assert not await repo.create_if_absent(other, "cid2", {})
    got = await repo.get("c_offside")
    assert got.concept.definition == "A rule of football." and got.source_cid == "cid1"
    assert isinstance(got.added_at, datetime)


async def test_since_filters_on_added_at():
    store = InMemoryDocStore()
    repo = GrowthRepo(store)
    await repo.create_if_absent(_concept("c_a"), "x", {})
    cutoff = datetime.now(UTC) - timedelta(seconds=1)
    assert [g.concept.id for g in await repo.since(cutoff)] == ["c_a"]
    assert await repo.since(datetime.now(UTC) + timedelta(seconds=5)) == []
    assert len(await repo.since(None)) == 1


async def test_slots_respect_both_caps_and_leave_the_ingest_counter_alone():
    store = InMemoryDocStore()
    repo, readers = GrowthRepo(store), ReaderRepo(store)
    day = "2026-10-10"
    assert await repo.reserve_slots("u1", day, 5, uid_cap=7, day_cap=100) == 5
    assert await readers.reserve_ingest("u1", day, 3, None, 30)
    assert await repo.reserve_slots("u1", day, 5, uid_cap=7, day_cap=100) == 2  # uid cap
    assert await repo.reserve_slots("u2", day, 5, uid_cap=7, day_cap=8) == 1  # day cap
    assert await repo.reserve_slots("u3", day, 5, uid_cap=7, day_cap=8) == 0
    assert store.docs["users/u1/growth_counts/2026-10-10"]["count"] == 7
    assert store.docs["users/u1/ingest_counts/2026-10-10"]["count"] == 1


async def test_growth_counts_are_exported_and_deleted_with_the_reader():
    store = InMemoryDocStore()
    await GrowthRepo(store).reserve_slots("u1", "2026-10-10", 3, 25, 100)
    readers = ReaderRepo(store)
    assert (await readers.export("u1"))["growth_counts"] == {
        "2026-10-10": {"count": 3, "day": "2026-10-10"}
    }
    await readers.delete("u1")
    assert not any(p.startswith("users/u1") for p in store.docs)
