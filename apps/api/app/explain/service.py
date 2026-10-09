"""Verified explanations (DESIGN §7): cache → generate → checks → judge → regenerate once →
definition-only card. Nothing unverified is ever returned as an explanation or cached.

Logs carry reason codes, models, cost and latency; never drafts or article text.
"""

import asyncio
import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from app import llm
from app.explain import checks
from app.explain.inputs import ExplainInputs
from app.explain.models import Explanation, Verdict
from app.store.explain_repo import ExplainRepo

log = logging.getLogger(__name__)

RunFn = Callable[..., Awaitable[llm.LLMResult[Any]]]
Kind = Literal["verified", "definition"]
Reason = Literal[
    "hit", "verified_first", "verified_retry", "rejected_twice", "judge_unavailable",
    "generate_unavailable", "budget", "capped",
]  # fmt: skip
LATENCY_WINDOW = 200
LATENCY_LOG_EVERY = 25


def prompt_version() -> str:
    return f"{llm.load_prompt('explain').version}+{llm.load_prompt('verify').version}"


@dataclass(frozen=True)
class VerifyResult:
    check_reasons: tuple[str, ...]
    judge_reasons: tuple[str, ...]
    judged: bool
    verdict: Verdict | None = None
    meta: llm.CallMeta | None = None

    @property
    def passed(self) -> bool:
        return self.judged and not self.check_reasons and not self.judge_reasons

    @property
    def reasons(self) -> tuple[str, ...]:
        return self.check_reasons + self.judge_reasons


@dataclass(frozen=True)
class Attempt:
    draft: Explanation
    meta: llm.CallMeta
    result: VerifyResult


@dataclass(frozen=True)
class Outcome:
    kind: Kind
    reason: Reason
    explanation: Explanation | None
    attempts: tuple[Attempt, ...] = ()

    @property
    def cacheable(self) -> bool:
        """Verified cards, and the definition after two rejected drafts (stores no draft).
        Never a transient failure: the judge or budget may be back on the next hover."""
        return self.kind == "verified" or self.reason == "rejected_twice"

    @property
    def cost_usd(self) -> float:
        return round(
            sum(a.meta.cost_usd + (a.result.meta.cost_usd if a.result.meta else 0.0)
                for a in self.attempts),
            8,
        )  # fmt: skip

    @property
    def models(self) -> dict[str, str | None]:
        last = self.attempts[-1] if self.attempts else None
        judged = next((a.result.meta for a in reversed(self.attempts) if a.result.meta), None)
        return {"explain": last.meta.model if last else None,
                "verify": judged.model if judged else None}  # fmt: skip


async def verify_draft(
    inputs: ExplainInputs, draft: Explanation, *, run: RunFn, always_judge: bool = False
) -> VerifyResult:
    """Deterministic checks, then the judge (skipped when the checks already failed, unless
    `always_judge`, which the evals use to see what each layer catches)."""
    reasons = tuple(checks.check(inputs, draft.author_says, draft.background))
    if reasons and not always_judge:
        return VerifyResult(reasons, (), judged=False)
    result = await run("verify", Verdict, inputs.verify_vars(draft.background, draft.author_says))
    verdict: Verdict = result.output
    return VerifyResult(reasons, tuple(verdict.reasons()), True, verdict, result.meta)


def _frame(draft: Explanation, inputs: ExplainInputs) -> Explanation:
    """An analogy is only allowed from the reader's own frame; drop a mismatched label."""
    if draft.analogy_domain is not None and draft.analogy_domain != inputs.thinks_in:
        return draft.model_copy(update={"analogy_domain": None})
    return draft


async def generate_verified(inputs: ExplainInputs, *, run: RunFn | None = None) -> Outcome:
    run = run or llm.run_with_meta
    attempts: list[Attempt] = []
    feedback = "none"
    for n in range(2):
        try:
            gen = await run("explain", Explanation, inputs.prompt_vars(feedback))
            draft = _frame(gen.output, inputs)
        except llm.BudgetExceeded:
            return Outcome("definition", "budget", None, tuple(attempts))
        except llm.LLMError:
            return Outcome("definition", "generate_unavailable", None, tuple(attempts))
        try:
            result = await verify_draft(inputs, draft, run=run)
        except llm.BudgetExceeded:
            return Outcome("definition", "budget", None, tuple(attempts))
        except llm.LLMError:  # verify never falls back (DESIGN §10): show the definition
            return Outcome("definition", "judge_unavailable", None, tuple(attempts))
        attempts.append(Attempt(draft, gen.meta, result))
        if result.passed:
            reason: Reason = "verified_first" if n == 0 else "verified_retry"
            return Outcome("verified", reason, draft, tuple(attempts))
        feedback = "\n".join(f"- {r}" for r in result.reasons)
    return Outcome("definition", "rejected_twice", None, tuple(attempts))


# ---------------------------------------------------------------- serving with the cache


@dataclass(frozen=True)
class Served:
    key: str
    kind: Kind
    reason: Reason
    explanation: Explanation | None
    cached: bool
    cost_usd: float = 0.0
    counts: dict[str, int] = field(default_factory=dict)  # ops/explain counters to add


def entry_doc(inputs: ExplainInputs, outcome: Outcome, version: str, now: datetime) -> dict:
    e = outcome.explanation
    return {
        "kind": outcome.kind,
        "reason": outcome.reason,
        "verified": outcome.kind == "verified",
        "mode": inputs.mode,
        "background": e.background if e else None,
        "author_says": e.author_says if e else None,
        "analogy_domain": e.analogy_domain if e else None,
        "content_id": inputs.content_id,
        "paragraph_id": inputs.paragraph_id,
        "concept_id": inputs.concept_id,
        "span_hash": inputs.span_hash,
        "band": inputs.band,
        "thinks_in": inputs.thinks_in,
        "style": inputs.style,
        "prompt_version": version,
        "models": outcome.models,
        "attempts": len(outcome.attempts),
        "cost_usd": outcome.cost_usd,
        "created_at": now,
    }


def _from_entry(key: str, doc: dict) -> Served:
    explanation = (
        Explanation(
            background=doc["background"],
            author_says=doc["author_says"],
            analogy_domain=doc.get("analogy_domain"),
        )
        if doc.get("kind") == "verified"
        else None
    )
    kind: Kind = "verified" if explanation else "definition"
    return Served(key, kind, "hit", explanation, cached=True, counts={"hits": 1})


_inflight: dict[str, asyncio.Task[Served]] = {}


async def serve(
    inputs: ExplainInputs,
    repo: ExplainRepo,
    *,
    reserve: Callable[[], Awaitable[bool]],
    refund: Callable[[], Awaitable[None]],
    run: RunFn | None = None,
) -> Served:
    """The cached card, or a new one. One generation per key per instance at a time: a
    prefetch and a hover on the same span share it. Only a new generation counts against the
    reader's daily cap (`reserve`), refunded if no model call could be made."""
    version = prompt_version()
    key = inputs.cache_key(version)
    entry = await repo.get(key)
    if entry is not None:
        return _from_entry(key, entry)
    if (task := _inflight.get(key)) is not None:
        shared = await asyncio.shield(task)
        return Served(key, shared.kind, shared.reason, shared.explanation, cached=False)
    if not await reserve():
        return Served(key, "definition", "capped", None, cached=False, counts={"capped": 1})

    async def fill() -> Served:
        outcome = await generate_verified(inputs, run=run)
        if outcome.reason in ("budget", "generate_unavailable") and not outcome.attempts:
            await refund()
        if outcome.cacheable:
            await repo.put(key, entry_doc(inputs, outcome, version, datetime.now(UTC)))
        _log(inputs, outcome, version)
        counts = {"generated": 1, outcome.reason: 1}
        return Served(
            key, outcome.kind, outcome.reason, outcome.explanation, cached=False,
            cost_usd=outcome.cost_usd, counts=counts,
        )  # fmt: skip

    task = asyncio.ensure_future(fill())
    _inflight[key] = task
    task.add_done_callback(lambda _: _inflight.pop(key, None))
    return await asyncio.shield(task)


def _log(inputs: ExplainInputs, outcome: Outcome, version: str) -> None:
    codes = [r.split(":", 1)[0] for a in outcome.attempts for r in a.result.reasons]
    log.info(
        "explanation generated",
        extra={
            "mode": inputs.mode,
            "kind": outcome.kind,
            "reason": outcome.reason,
            "attempts": len(outcome.attempts),
            "reason_codes": codes,
            "models": outcome.models,
            "prompt_version": version,
            "cost_usd": outcome.cost_usd,
            "band": inputs.band,
            "thinks_in": inputs.thinks_in,
            "style": inputs.style,
        },
    )


# ---------------------------------------------------------------- latency (cached vs generated)

_latency: dict[str, deque[float]] = {
    "cached": deque(maxlen=LATENCY_WINDOW),
    "generated": deque(maxlen=LATENCY_WINDOW),
}
_served = 0


def percentile(samples: list[float], q: float) -> float:
    ordered = sorted(samples)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))] if ordered else 0.0


class Timer:
    def __init__(self) -> None:
        self.started = time.perf_counter()

    def ms(self) -> float:
        return round((time.perf_counter() - self.started) * 1000, 1)


def record_latency(cached: bool, ms: float) -> None:
    """Rolling p50/p95 per class, logged every LATENCY_LOG_EVERY requests."""
    global _served
    _latency["cached" if cached else "generated"].append(ms)
    _served += 1
    if _served % LATENCY_LOG_EVERY == 0:
        fields: dict[str, float] = {}
        for name, window in _latency.items():
            samples = list(window)
            fields[f"{name}_p50_ms"] = percentile(samples, 0.5)
            fields[f"{name}_p95_ms"] = percentile(samples, 0.95)
            fields[f"{name}_n"] = len(samples)
        log.info("explanation latency", extra=fields)
