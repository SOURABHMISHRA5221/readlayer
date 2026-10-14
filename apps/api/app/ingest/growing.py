"""One run of concept growth on a page, for phase 2 and for a reopen (M9 part 1, DESIGN §2).

Both callers hand in the page's demands and a `take(want) -> granted` that reserves slots for the
reader (or uses slots an older pending doc already holds). Order: untried labels → time left →
reserve exactly what will be tried → grow. Nothing is reserved for a page with nothing to try or
no time, and there is nothing to refund afterwards: growth spends one define call per label.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

from app import llm
from app.config import get_settings
from app.graph.build import normalize_label
from app.graph.growth import pick
from app.graph.growth_need import untried_count
from app.graph.loader import get_graph
from app.ingest.models import ContentDoc, Demand, LLMCall
from app.ingest.quota import Reserver

log = logging.getLogger("app.ingest")

CLAIM_MARGIN_S = 30  # a claim outlives the growth timeout, so a live grower never loses it


@dataclass(frozen=True)
class GrowthResult:
    demands: list[Demand]
    calls: list[LLMCall]
    pending: bool  # the caps (or the clock, or a transient error) cut growth short
    tried: list[str]  # normalised labels tried on this page, never tried again
    budget_refused: bool = False
    linked: int = field(default=0)  # demands this run linked
    granted: int = 0  # slots the caps gave this run


async def run_growth(
    content_id: str,
    demands: list[Demand],
    paragraphs: dict[str, str],
    tried: list[str],
    budget_s: float,
    take: Reserver,
) -> GrowthResult:
    exclude = frozenset(tried)
    want = untried_count(demands, exclude, get_settings().growth_per_article)
    if not want:
        return GrowthResult(demands, [], False, list(tried))
    if budget_s <= 0:
        return GrowthResult(demands, [], True, list(tried))
    if await llm.get_spend_store().get_today() >= get_settings().llm_daily_budget_usd:
        # The calls would be refused: keep the reader's slots and the page pending.
        return GrowthResult(demands, [], True, list(tried), budget_refused=True)
    granted = await take(want)
    if granted <= 0:
        return GrowthResult(demands, [], True, list(tried))
    labels = [normalize_label(p.label) for p in pick(demands, paragraphs, granted, exclude)]
    from app.graph.grow import grow
    from app.graph.refresh import get_refresher
    from app.store.growth_repo import get_growth_repo

    started = time.perf_counter()
    try:
        async with asyncio.timeout(budget_s):
            outcome = await grow(
                get_graph(), demands, paragraphs, granted, content_id, get_growth_repo(),
                exclude=exclude,
            )  # fmt: skip
    except (llm.BudgetExceeded, llm.LLMUnavailable) as exc:  # nothing billed; worth another try
        _skipped(content_id, exc, started, budget_s)
        return GrowthResult(
            demands,
            [],
            True,
            list(tried),
            budget_refused=isinstance(exc, llm.BudgetExceeded),
            granted=granted,
        )
    except Exception as exc:  # model output, the timeout: billed, so these labels are done
        _skipped(content_id, exc, started, budget_s)
        return GrowthResult(demands, [], False, [*tried, *labels], granted=granted)
    get_refresher().apply(outcome.added)
    log.info(
        "concept growth",
        extra={
            "content_id": content_id,
            "wanted": want,
            "granted": granted,
            "added": len(outcome.added),
            "merged": outcome.merged,
            "rejected": outcome.rejected,
            "cost_usd": round(outcome.cost_usd, 6),
            "growth_ms": round((time.perf_counter() - started) * 1000),
        },
    )
    linked = [
        d.model_copy(update={"target_id": outcome.links[d.id], "grown": d.id in outcome.grown})
        if d.id in outcome.links
        else d
        for d in demands
    ]
    return GrowthResult(
        linked,
        [llm_call(m) for m in outcome.calls],
        granted < want,
        [*tried, *labels],
        linked=len(outcome.links),
        granted=granted,
    )


def _skipped(content_id: str, exc: BaseException, started: float, budget_s: float) -> None:
    log.warning(
        "concept growth skipped",
        extra={
            "content_id": content_id,
            "error_class": type(exc).__name__,
            "growth_ms": round((time.perf_counter() - started) * 1000),
            "budget_s": round(budget_s, 1),
        },
    )


def llm_call(m: llm.CallMeta) -> LLMCall:
    return LLMCall(
        task=m.task,
        model=m.model,
        prompt_version=m.prompt_version,
        tokens_in=m.tokens_in,
        tokens_out=m.tokens_out,
        cost_usd=m.cost_usd,
        fell_back=m.fell_back,
    )


@dataclass(frozen=True)
class Regrown:
    status: Literal["none", "capped", "grown", "growing", "budget"]
    linked: int = 0


async def grow_stored(doc: ContentDoc, reserve: Reserver | None) -> Regrown:
    """POST /v1/content/{id}/grow (M9 part 1, G4–G7): grow a reader's stored page that missed
    growth. No model call unless `needs_growth`; one grower per page across instances; a run
    that outlived its claim writes nothing. The page's text never changes, only demand links."""
    from app.content import catalog
    from app.graph.growth_need import needs_growth
    from app.graph.heldout import is_heldout
    from app.store.content_repo import get_content_store

    settings = get_settings()
    if reserve is None or not needs_growth(doc, heldout=is_heldout(doc.content_id)):
        return Regrown("none")
    store = get_content_store()
    now = datetime.now(UTC)
    until = now + timedelta(seconds=settings.growth_timeout_s + CLAIM_MARGIN_S)
    status, token = await store.claim_growth(doc.content_id, now, until)
    if status != "claimed" or token is None:
        return Regrown("growing" if status == "busy" else "none")
    tried = doc.grow_tried
    try:
        # Read again under the claim: another grower may have finished since the caller's read.
        fresh = await store.get(doc.content_id)
        tried = fresh.grow_tried if fresh is not None else tried
        if fresh is None or not needs_growth(fresh, heldout=False):
            await store.finish_growth(doc.content_id, token, None, [], False, tried)
            return Regrown("none")
        paragraphs = {p.id: p.text for p in fresh.paragraphs}
        result = await run_growth(
            fresh.content_id, fresh.demands, paragraphs, fresh.grow_tried,
            settings.growth_timeout_s, reserve,
        )  # fmt: skip
    except BaseException:  # release the claim at once, the page still pending; then re-raise
        await asyncio.shield(store.finish_growth(doc.content_id, token, None, [], True, tried))
        raise
    demands = result.demands if result.linked else None
    if not await store.finish_growth(
        doc.content_id, token, demands, result.calls, result.pending, result.tried
    ):
        log.warning(
            "concept growth result dropped: claim lost",
            extra={
                "content_id": doc.content_id,
                "cost_usd": round(sum(c.cost_usd for c in result.calls), 6),
            },
        )
        return Regrown("none")
    if result.budget_refused:
        return Regrown("budget")
    if result.linked and (fresh := await store.get(doc.content_id)) is not None:
        catalog.replace(fresh)
        return Regrown("grown", result.linked)
    return Regrown("capped" if result.pending and not result.granted else "none")
