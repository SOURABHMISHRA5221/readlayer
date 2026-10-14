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

from app import llm
from app.config import get_settings
from app.graph.build import normalize_label
from app.graph.growth import pick, untried_count
from app.graph.loader import get_graph
from app.ingest.models import Demand, LLMCall
from app.ingest.quota import Reserver

log = logging.getLogger("app.ingest")


@dataclass(frozen=True)
class GrowthResult:
    demands: list[Demand]
    calls: list[LLMCall]
    pending: bool  # the caps (or the clock, or a transient error) cut growth short
    tried: list[str]  # normalised labels tried on this page, never tried again
    budget_refused: bool = False
    linked: int = field(default=0)  # demands this run linked


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
            demands, [], True, list(tried), budget_refused=isinstance(exc, llm.BudgetExceeded)
        )
    except Exception as exc:  # model output, the timeout: billed, so these labels are done
        _skipped(content_id, exc, started, budget_s)
        return GrowthResult(demands, [], False, [*tried, *labels])
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
