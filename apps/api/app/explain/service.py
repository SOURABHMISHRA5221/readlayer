"""Verified explanations (DESIGN §7), in two parts, each generated, verified and cached on its own:

- the restatement ("What the author is saying"): `restate` → deterministic checks → claims
  judge (`verify`) → regenerate once. Keyed by (span, style): made once, shared by every reader.
- the Background: `explain` → link check → Background judge (`verify_background`) → regenerate
  once. Keyed by (span, band, frame, style): the only per-reader part.

On a miss both run at the same time. A rejected restatement means the definition-only card; a
rejected Background means the verified restatement with the definition in the Background panel.
Nothing unverified is ever returned or cached. Logs carry reason codes, models, cost and
latency; never drafts or article text.
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
from app.explain.models import (
    BackgroundDraft,
    BackgroundVerdict,
    Card,
    Explanation,
    Restatement,
    Verdict,
)
from app.store.explain_repo import ExplainRepo

log = logging.getLogger(__name__)

RunFn = Callable[..., Awaitable[llm.LLMResult[Any]]]
Kind = Literal["verified", "definition"]
Part = Literal["restatement", "background"]
PartReason = Literal[
    "verified_first", "verified_retry", "rejected_twice", "judge_unavailable",
    "generate_unavailable", "budget",
]  # fmt: skip
Reason = Literal[PartReason, "hit", "capped"]
LATENCY_WINDOW = 200
LATENCY_LOG_EVERY = 25


def restate_version() -> str:
    return f"{llm.load_prompt('restate').version}+{llm.load_prompt('verify').version}"


def background_version() -> str:
    return f"{llm.load_prompt('explain').version}+{llm.load_prompt('verify_background').version}"


def prompt_version() -> str:
    return f"{restate_version()}|{background_version()}"


def card_id(restate_key: str, background_key: str) -> str:
    """What the client holds and "This is wrong" names: both entries."""
    return f"{restate_key}-{background_key}"


def split_card_id(card: str) -> list[str]:
    return card.split("-")


@dataclass(frozen=True)
class VerifyResult:
    check_reasons: tuple[str, ...]
    judge_reasons: tuple[str, ...]
    judged: bool
    metas: tuple[llm.CallMeta, ...] = ()

    @property
    def passed(self) -> bool:
        return self.judged and not self.check_reasons and not self.judge_reasons

    @property
    def reasons(self) -> tuple[str, ...]:
        return self.check_reasons + self.judge_reasons

    @property
    def cost_usd(self) -> float:
        return sum(m.cost_usd for m in self.metas)


async def verify_restatement(
    inputs: ExplainInputs, author_says: str, *, run: RunFn, always_judge: bool = False
) -> VerifyResult:
    """Deterministic checks, then the claims judge (skipped when the checks already failed,
    unless `always_judge`, which the evals use to see what each layer catches)."""
    reasons = tuple(checks.check_restatement(inputs, author_says))
    if reasons and not always_judge:
        return VerifyResult(reasons, (), judged=False)
    result = await run("verify", Verdict, inputs.verify_vars(author_says))
    return VerifyResult(reasons, tuple(result.output.reasons()), True, (result.meta,))


async def verify_background(
    inputs: ExplainInputs, background: str, *, run: RunFn, always_judge: bool = False
) -> VerifyResult:
    reasons = tuple(checks.check_background(inputs, background))
    if reasons and not always_judge:
        return VerifyResult(reasons, (), judged=False)
    result = await run(
        "verify_background", BackgroundVerdict, inputs.verify_background_vars(background)
    )
    return VerifyResult(reasons, tuple(result.output.reasons()), True, (result.meta,))


async def verify_draft(
    inputs: ExplainInputs, draft: Explanation, *, run: RunFn, always_judge: bool = False
) -> VerifyResult:
    """A whole card (the eval cases hold whole cards): each part to its own verifier."""
    r, b = await asyncio.gather(
        verify_restatement(inputs, draft.author_says, run=run, always_judge=always_judge),
        verify_background(inputs, draft.background, run=run, always_judge=always_judge),
    )
    return VerifyResult(
        r.check_reasons + b.check_reasons,
        r.judge_reasons + b.judge_reasons,
        r.judged and b.judged,
        r.metas + b.metas,
    )


@dataclass(frozen=True)
class Attempt:
    part: Part
    draft: Restatement | BackgroundDraft
    meta: llm.CallMeta
    result: VerifyResult


@dataclass(frozen=True)
class PartOutcome:
    part: Part
    reason: PartReason
    text: str | None = None  # author_says or background, only when verified
    analogy_domain: str | None = None
    attempts: tuple[Attempt, ...] = ()

    @property
    def verified(self) -> bool:
        return self.reason in ("verified_first", "verified_retry")

    @property
    def cacheable(self) -> bool:
        """Verified, or rejected twice (stores no draft). Never a transient failure: the judge
        or budget may be back on the next hover."""
        return self.verified or self.reason == "rejected_twice"

    @property
    def nothing_ran(self) -> bool:
        return not self.attempts and self.reason in ("budget", "generate_unavailable")

    @property
    def cost_usd(self) -> float:
        return sum(a.meta.cost_usd + a.result.cost_usd for a in self.attempts)


def _frame(draft: BackgroundDraft, inputs: ExplainInputs) -> BackgroundDraft:
    """An analogy is only allowed from the reader's own frame; drop a mismatched label."""
    if draft.analogy_domain is not None and draft.analogy_domain != inputs.thinks_in:
        return draft.model_copy(update={"analogy_domain": None})
    return draft


async def _draft(part: Part, inputs: ExplainInputs, feedback: str, run: RunFn):
    if part == "restatement":
        gen = await run("restate", Restatement, inputs.restate_vars(feedback))
        return gen.output, gen.meta
    gen = await run("explain", BackgroundDraft, inputs.prompt_vars(feedback))
    return _frame(gen.output, inputs), gen.meta


async def _verify(part: Part, inputs: ExplainInputs, draft: Any, run: RunFn) -> VerifyResult:
    if part == "restatement":
        return await verify_restatement(inputs, draft.author_says, run=run)
    return await verify_background(inputs, draft.background, run=run)


async def generate_part(part: Part, inputs: ExplainInputs, *, run: RunFn) -> PartOutcome:
    attempts: list[Attempt] = []
    feedback = "none"
    for n in range(2):
        try:
            draft, meta = await _draft(part, inputs, feedback, run)
        except llm.BudgetExceeded:
            return PartOutcome(part, "budget", attempts=tuple(attempts))
        except llm.LLMError:
            return PartOutcome(part, "generate_unavailable", attempts=tuple(attempts))
        try:
            result = await _verify(part, inputs, draft, run)
        except llm.BudgetExceeded:
            return PartOutcome(part, "budget", attempts=tuple(attempts))
        except llm.LLMError:  # judges never fall back (DESIGN §10): show the definition
            return PartOutcome(part, "judge_unavailable", attempts=tuple(attempts))
        attempts.append(Attempt(part, draft, meta, result))
        if result.passed:
            text = draft.author_says if part == "restatement" else draft.background
            frame = getattr(draft, "analogy_domain", None)
            reason: PartReason = "verified_first" if n == 0 else "verified_retry"
            return PartOutcome(part, reason, text, frame, tuple(attempts))
        feedback = "\n".join(f"- {r}" for r in result.reasons)
    return PartOutcome(part, "rejected_twice", attempts=tuple(attempts))


@dataclass(frozen=True)
class Outcome:
    """A whole card from both parts (either may have come from the cache: None here)."""

    kind: Kind
    reason: Reason
    explanation: Card | None
    restatement: PartOutcome | None = None
    background: PartOutcome | None = None

    @property
    def attempts(self) -> tuple[Attempt, ...]:
        parts = (self.restatement, self.background)
        return tuple(a for p in parts if p for a in p.attempts)

    @property
    def cost_usd(self) -> float:
        return round(sum(p.cost_usd for p in (self.restatement, self.background) if p), 8)

    @property
    def models(self) -> dict[str, str | None]:
        def last(task_part: Part, judge: bool) -> str | None:
            for a in reversed(self.attempts):
                if a.part == task_part:
                    if not judge:
                        return a.meta.model
                    if a.result.metas:
                        return a.result.metas[-1].model
            return None

        return {
            "restate": last("restatement", False),
            "explain": last("background", False),
            "verify": last("restatement", True) or last("background", True),
        }


def compose(
    author_says: str | None,
    background: str | None,
    analogy: str | None,
    reason: Reason,
    restatement: PartOutcome | None = None,
    background_part: PartOutcome | None = None,
) -> Outcome:
    """The served card (DESIGN §7): no verified restatement → definition only; a verified
    restatement without a verified Background → the definition stays in that panel."""
    if author_says is None:
        return Outcome("definition", reason, None, restatement, background_part)
    card = Card(
        background=background,
        author_says=author_says,
        analogy_domain=analogy if background else None,
    )
    return Outcome("verified", reason, card, restatement, background_part)


async def generate_verified(inputs: ExplainInputs, *, run: RunFn | None = None) -> Outcome:
    """Both parts from scratch, at the same time (the evals and the demo script use this)."""
    run = run or llm.run_with_meta
    r, b = await asyncio.gather(
        generate_part("restatement", inputs, run=run),
        generate_part("background", inputs, run=run),
    )
    return compose(r.text, b.text, b.analogy_domain, r.reason, r, b)


# ---------------------------------------------------------------- serving with the cache


@dataclass(frozen=True)
class Served:
    key: str
    kind: Kind
    reason: Reason
    explanation: Card | None
    cached: bool
    cost_usd: float = 0.0
    counts: dict[str, int] = field(default_factory=dict)  # ops/explain counters to add


def _base(inputs: ExplainInputs, outcome: PartOutcome, version: str, now: datetime) -> dict:
    last = outcome.attempts[-1] if outcome.attempts else None
    judged = next((a.result.metas[-1] for a in reversed(outcome.attempts) if a.result.metas), None)
    return {
        "part": outcome.part,
        "kind": "verified" if outcome.verified else "definition",
        "reason": outcome.reason,
        "verified": outcome.verified,
        "mode": inputs.mode,
        "content_id": inputs.content_id,
        "paragraph_id": inputs.paragraph_id,
        "concept_id": inputs.concept_id,
        "span_hash": inputs.span_hash,
        "style": inputs.style,
        "prompt_version": version,
        "models": {
            "generate": last.meta.model if last else None,
            "verify": judged.model if judged else None,
        },
        "attempts": len(outcome.attempts),
        "cost_usd": round(outcome.cost_usd, 8),
        "created_at": now,
    }


def restatement_doc(
    inputs: ExplainInputs, outcome: PartOutcome, version: str, now: datetime
) -> dict:
    """Shared by every reader: no band, no frame."""
    return _base(inputs, outcome, version, now) | {"author_says": outcome.text}


def background_doc(
    inputs: ExplainInputs, outcome: PartOutcome, version: str, now: datetime
) -> dict:
    return _base(inputs, outcome, version, now) | {
        "background": outcome.text,
        "analogy_domain": outcome.analogy_domain if outcome.text else None,
        "band": inputs.band,
        "thinks_in": inputs.thinks_in,
    }


def _text(entry: dict | None, field_name: str) -> str | None:
    return entry.get(field_name) if entry and entry.get("verified") else None


_inflight: dict[str, asyncio.Task[Served]] = {}


async def _none() -> None:
    return None


async def serve(
    inputs: ExplainInputs,
    repo: ExplainRepo,
    *,
    reserve: Callable[[], Awaitable[bool]],
    refund: Callable[[], Awaitable[None]],
    run: RunFn | None = None,
) -> Served:
    """The cached card, or the missing parts made now. One generation per card per instance at
    a time (a prefetch and a hover share it). A request that generates anything counts once
    against the reader's daily cap (`reserve`), refunded if no model call could be made."""
    rv, bv = restate_version(), background_version()
    rkey, bkey = inputs.restate_key(rv), inputs.background_key(bv)
    key = card_id(rkey, bkey)
    r_entry, b_entry = await asyncio.gather(repo.get(rkey), repo.get(bkey))
    need_r = r_entry is None
    # A rejected restatement means a definition card: no Background is worth making.
    need_b = b_entry is None and (r_entry is None or bool(r_entry.get("verified")))
    if not need_r and not need_b:
        out = compose(
            _text(r_entry, "author_says"),
            _text(b_entry, "background"),
            (b_entry or {}).get("analogy_domain"),
            "hit",
        )
        return Served(key, out.kind, "hit", out.explanation, cached=True, counts={"hits": 1})
    if (task := _inflight.get(key)) is not None:
        shared = await asyncio.shield(task)
        return Served(key, shared.kind, shared.reason, shared.explanation, cached=False)
    if not await reserve():
        # Past the cap: a shared restatement still shows; the Background stays the definition.
        out = compose(_text(r_entry, "author_says"), None, None, "capped")
        return Served(key, out.kind, "capped", out.explanation, cached=False, counts={"capped": 1})

    async def fill() -> Served:
        run_ = run or llm.run_with_meta
        r_out, b_out = await asyncio.gather(
            generate_part("restatement", inputs, run=run_) if need_r else _none(),
            generate_part("background", inputs, run=run_) if need_b else _none(),
        )
        made = [p for p in (r_out, b_out) if p is not None]
        if all(p.nothing_ran for p in made):
            await refund()
        now = datetime.now(UTC)
        if r_out is not None and r_out.cacheable:
            await repo.put(rkey, restatement_doc(inputs, r_out, rv, now))
        if b_out is not None and b_out.cacheable:
            await repo.put(bkey, background_doc(inputs, b_out, bv, now))
        author_says = r_out.text if r_out is not None else _text(r_entry, "author_says")
        background = b_out.text if b_out is not None else _text(b_entry, "background")
        analogy = (
            b_out.analogy_domain if b_out is not None else (b_entry or {}).get("analogy_domain")
        )
        reason: Reason = (r_out or b_out).reason  # type: ignore[union-attr]
        out = compose(author_says, background, analogy, reason, r_out, b_out)
        for p in made:
            _log(inputs, p)
        counts = {"generated": 1} | {f"{p.part}_{p.reason}": 1 for p in made}
        return Served(
            key, out.kind, out.reason, out.explanation, cached=False,
            cost_usd=out.cost_usd, counts=counts,
        )  # fmt: skip

    task = asyncio.ensure_future(fill())
    _inflight[key] = task
    task.add_done_callback(lambda _: _inflight.pop(key, None))
    return await asyncio.shield(task)


def _log(inputs: ExplainInputs, outcome: PartOutcome) -> None:
    codes = [r.split(":", 1)[0] for a in outcome.attempts for r in a.result.reasons]
    log.info(
        "explanation part generated",
        extra={
            "part": outcome.part,
            "mode": inputs.mode,
            "verified": outcome.verified,
            "reason": outcome.reason,
            "attempts": len(outcome.attempts),
            "reason_codes": codes,
            "prompt_version": restate_version()
            if outcome.part == "restatement"
            else background_version(),
            "cost_usd": round(outcome.cost_usd, 8),
            "band": inputs.band if outcome.part == "background" else None,
            "thinks_in": inputs.thinks_in if outcome.part == "background" else None,
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
