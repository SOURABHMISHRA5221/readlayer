"""M9 G11: the read-only count of stored pages a reopen would grow, before the API deploy."""

from app.store.content_repo import InMemoryContentStore
from scripts import growth_backlog
from tests.test_growth_phase2 import demands
from tests.test_growth_reopen import page


async def test_counts_eligible_pages_by_source_and_the_worst_case():
    store = InMemoryContentStore()
    for cid, kw in {
        "a1": {"demands": demands("A", "B", "C", "D", "E", "F")},  # old extension page: 5 slots
        "a2": {"grow_pending": True, "demands": demands("A")},
        "a3": {"source": "user_ingested", "grow_pending": False},
        "a4": {"source": "fetch", "grow_pending": True},  # corpus: never
    }.items():
        doc = page(**kw).model_copy(update={"content_id": cid})
        store.docs[cid] = doc
    report = await growth_backlog.count(store)
    assert report.pages == {"extension": 2}
    assert report.slots == 6 and report.scanned == 4
    assert report.worst_usd == round(2 * 0.0127, 4) and report.mean_usd == round(2 * 0.0050, 4)
