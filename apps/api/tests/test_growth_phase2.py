"""M9 part 1: phase 2 reserves exactly what growth will try, and marks pages that missed it."""

import asyncio
from pathlib import Path

import pytest

from app import config, llm
from app.graph.grow import GrowthOutcome
from app.graph.heldout import heldout_ids
from app.ingest import service
from app.ingest.extract import build_paragraphs
from app.ingest.models import Anchor, Demand
from scripts.ingest_corpus import parse_corpus
from tests import test_growth_wiring as wiring
from tests.test_growth_wiring import HELDOUT, _pending, concept

env = wiring.env  # the wiring tests' fixture: in-memory stores, a one-concept graph, growth on
HELDOUT_URL = next(iter(parse_corpus(Path(HELDOUT).read_text().splitlines()))).url


def demands(*labels):
    anchor = Anchor(exact="x", prefix="", suffix="", start=0, end=1)
    return [
        Demand(id=f"d{i}", paragraph_id="p0", type="concept", label=label,
               salience=0.9 - i / 10, explained_in_text=False, zipf=3.0, anchor=anchor)
        for i, label in enumerate(labels)
    ]  # fmt: skip


class Grower:
    """Fake grow(): records slots and exclude, links every picked demand to a new concept."""

    def __init__(self, error: Exception | None = None):
        self.calls: list[tuple[int, frozenset]] = []
        self.error = error

    async def __call__(
        self, graph, ds, paragraphs, slots, source_cid, repo, *a, exclude=frozenset(), **k
    ):
        self.calls.append((slots, exclude))
        if self.error:
            raise self.error
        picked = [d for d in ds if d.target_id is None][:slots]
        return GrowthOutcome(
            links={d.id: f"c_{d.label.lower()}" for d in picked},
            grown={d.id for d in picked},
            added=[concept(f"c_{d.label.lower()}", d.label) for d in picked],
        )


class Reserver:
    def __init__(self, grant: int | None = None):
        self.asked: list[int] = []
        self.grant = grant

    async def __call__(self, want: int) -> int:
        self.asked.append(want)
        return want if self.grant is None else min(want, self.grant)


async def run(pending, ds, reserve, deadline=float("inf")):
    paragraphs = build_paragraphs([p.text for p in pending.paragraphs])
    return await service._grow(pending, ds, paragraphs, deadline, reserve)


async def test_reserves_exactly_the_labels_it_will_try(env, monkeypatch):
    grower, reserve = Grower(), Reserver()
    monkeypatch.setattr("app.graph.grow.grow", grower)
    got = await run(_pending(slots=0), demands("Offside", "Pressing"), reserve)
    assert reserve.asked == [2] and grower.calls == [(2, frozenset())]
    assert [d.target_id for d in got.demands] == ["c_offside", "c_pressing"]
    assert got.pending is False and got.tried == ["offside", "pressing"]


async def test_a_page_with_nothing_to_grow_reserves_nothing(env, monkeypatch):
    grower, reserve = Grower(), Reserver()
    monkeypatch.setattr("app.graph.grow.grow", grower)
    linked = demands("Goal")[0].model_copy(update={"target_id": "c_goal"})
    got = await run(_pending(slots=0), [linked], reserve)
    assert reserve.asked == [] and grower.calls == [] and got.pending is False


async def test_a_partial_grant_leaves_the_page_pending(env, monkeypatch):
    grower, reserve = Grower(), Reserver(grant=1)
    monkeypatch.setattr("app.graph.grow.grow", grower)
    got = await run(_pending(slots=0), demands("Offside", "Pressing"), reserve)
    assert grower.calls == [(1, frozenset())]
    assert got.pending is True and got.tried == ["offside"]


async def test_no_grant_leaves_the_page_pending_with_nothing_tried(env, monkeypatch):
    grower, reserve = Grower(), Reserver(grant=0)
    monkeypatch.setattr("app.graph.grow.grow", grower)
    got = await run(_pending(slots=0), demands("Offside"), reserve)
    assert grower.calls == [] and got.pending is True and got.tried == []


async def test_out_of_time_reserves_nothing_and_stays_pending(env, monkeypatch):
    grower, reserve = Grower(), Reserver()
    monkeypatch.setattr("app.graph.grow.grow", grower)
    deadline = asyncio.get_running_loop().time() + 1
    got = await run(_pending(slots=0), demands("Offside"), reserve, deadline)
    assert reserve.asked == [] and grower.calls == [] and got.pending is True


@pytest.mark.parametrize(
    ("error", "pending", "tried"),
    [
        (llm.BudgetExceeded("over"), True, []),  # nothing billed, transient
        (llm.LLMUnavailable("down"), True, []),
        (RuntimeError("bad output"), False, ["offside"]),  # billed: not tried again
        (TimeoutError(), False, ["offside"]),
    ],
)
async def test_growth_failures_by_kind(env, monkeypatch, error, pending, tried):
    monkeypatch.setattr("app.graph.grow.grow", Grower(error))
    got = await run(_pending(slots=0), demands("Offside"), Reserver())
    assert got.demands == demands("Offside") and got.calls == []
    assert got.pending is pending and got.tried == tried
    assert got.budget_refused is isinstance(error, llm.BudgetExceeded)


async def test_scripts_reserve_nothing_and_mark_the_page_done(env, monkeypatch):
    grower = Grower()
    monkeypatch.setattr("app.graph.grow.grow", grower)
    got = await run(_pending(slots=0), demands("Offside"), None)
    assert grower.calls == [] and got.pending is False


async def test_a_pending_doc_from_before_m9_uses_its_own_slots(env, monkeypatch):
    grower, reserve = Grower(), Reserver()
    monkeypatch.setattr("app.graph.grow.grow", grower)
    got = await run(_pending(slots=1), demands("Offside", "Pressing"), reserve)
    assert reserve.asked == [] and grower.calls == [(1, frozenset())]
    assert got.tried == ["offside"] and got.pending is True


@pytest.mark.parametrize("case", ["off", "heldout"])
async def test_off_or_heldout_never_grows(env, monkeypatch, case):
    grower, reserve = Grower(), Reserver()
    monkeypatch.setattr("app.graph.grow.grow", grower)
    url = HELDOUT_URL if case == "heldout" else "https://news.test/b"
    if case == "off":
        monkeypatch.setenv("GROWTH_ENABLED", "false")
        config.get_settings.cache_clear()
    got = await run(_pending(url, slots=0), demands("Offside"), reserve)
    assert reserve.asked == [] and grower.calls == [] and got.pending is False
    assert case != "heldout" or _pending(url).content_id in heldout_ids()


async def test_over_the_daily_budget_reserves_nothing(env, monkeypatch):
    """Review round 1, item 8: once the $8 guard trips, a reopen must not burn the reader's
    slots on calls that would be refused anyway."""
    from app import llm as llm_module
    from app.store.spend_repo import InMemorySpendStore

    spend = InMemorySpendStore()
    await spend.add(9.0, 0, 0)
    llm_module.set_spend_store(spend)
    try:
        grower, reserve = Grower(), Reserver()
        monkeypatch.setattr("app.graph.grow.grow", grower)
        got = await run(_pending(slots=0), demands("Offside"), reserve)
        assert reserve.asked == [] and grower.calls == []
        assert got.pending is True and got.budget_refused is True
    finally:
        llm_module.set_spend_store(None)
