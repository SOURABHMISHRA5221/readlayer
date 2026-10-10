"""LLM passes of the concept build: merge checks, definitions, prerequisites, Wikipedia matches.

Each pass batches items, validates the structured reply against the batch (unknown numbers are
ignored), and re-asks once for items the model skipped. Calls go through an injected `runner`
(llm.run_with_meta, or a caching wrapper in the build script) so tests need no network.
"""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field

from app import llm
from app.graph.build import KINDS, Prereq
from app.graph.models import Domain

Runner = Callable[[str, type[BaseModel], dict[str, Any]], Awaitable[llm.LLMResult[Any]]]
Kind = Literal[tuple(sorted(KINDS))]  # type: ignore[valid-type]
CONCURRENCY = 4
# link_confirm runs on MODEL_QUALITY, which took ~19.5 s for 20 mentions (timeout 20 s):
# smaller batches stay well under the timeout, more of them run in parallel.
LINK_BATCH, LINK_CONCURRENCY = 10, 8
SNIPPET_CHARS = 220


# ---------------------------------------------------------------- schemas


class MergeDecision(BaseModel):
    pair: int
    same: bool


class MergeDecisions(BaseModel):
    decisions: list[MergeDecision]


class ConceptInfo(BaseModel):
    id: int
    definition: str = Field(min_length=10, max_length=500)
    specialization: int = Field(ge=1, le=5)
    domain: Domain
    kind: Kind
    # concept_define-v3 (M2.2); v2 cached outputs have none, so they read as global.
    jurisdiction: str = Field(default="global", pattern=r"^([A-Z]{2}|global)$")


class ConceptInfos(BaseModel):
    concepts: list[ConceptInfo]


class PrereqPick(BaseModel):
    id: str
    confidence: float = Field(ge=0, le=1)


class ConceptPrereqs(BaseModel):
    concept: int
    prerequisites: list[PrereqPick] = Field(default_factory=list, max_length=6)


class PrereqBatch(BaseModel):
    concepts: list[ConceptPrereqs]


class WikiMatch(BaseModel):
    id: int
    same: bool


class WikiMatches(BaseModel):
    matches: list[WikiMatch]


class LinkAnswer(BaseModel):
    mention: int
    concept_id: str | None = None


class LinkAnswers(BaseModel):
    answers: list[LinkAnswer]


# ---------------------------------------------------------------- inputs


@dataclass(frozen=True)
class Entry:
    """A concept candidate as the model sees it."""

    label: str
    aliases: tuple[str, ...] = ()
    snippets: tuple[str, ...] = ()
    definition: str = ""


@dataclass(frozen=True)
class PrereqRequest:
    entry: Entry
    candidates: tuple[tuple[str, str], ...]  # (concept id, label)


@dataclass(frozen=True)
class LinkQuestion:
    """One mention for the model to resolve against its candidate concepts."""

    demand_id: str
    phrase: str
    sentence: str
    candidates: tuple[tuple[str, str, str, float], ...]  # (id, label, definition, cosine)


@dataclass(frozen=True)
class WikiCandidate:
    entry: Entry
    title: str
    description: str


# ---------------------------------------------------------------- rendering


def _also(entry: Entry) -> str:
    return f" (also: {', '.join(entry.aliases[:5])})" if entry.aliases else ""


def render_pairs(pairs: Sequence[tuple[Entry, Entry]]) -> str:
    return "\n".join(
        f'[{i}] "{a.label}"{_also(a)}  |  "{b.label}"{_also(b)}' for i, (a, b) in enumerate(pairs)
    )


def render_entries(entries: Sequence[Entry]) -> str:
    lines = []
    for i, e in enumerate(entries):
        lines.append(f"[{i}] {e.label}{_also(e)}")
        lines.extend(f"    context: {s[:SNIPPET_CHARS]}" for s in e.snippets[:2])
    return "\n".join(lines)


def render_prereq_requests(requests: Sequence[PrereqRequest]) -> str:
    blocks = []
    for i, r in enumerate(requests):
        cands = "; ".join(f"{cid} {label}" for cid, label in r.candidates)
        blocks.append(f"[{i}] {r.entry.label}: {r.entry.definition}\n    candidates: {cands}")
    return "\n".join(blocks)


def render_wiki(items: Sequence[WikiCandidate]) -> str:
    return "\n".join(
        f"[{i}] concept: {c.entry.label}: {c.entry.definition}\n"
        f"    wikipedia: {c.title}: {c.description or '(no description)'}"
        for i, c in enumerate(items)
    )


def render_link_questions(questions: Sequence[LinkQuestion]) -> str:
    blocks = []
    for i, q in enumerate(questions):
        lines = [f"[{i}] phrase: {q.phrase}", f"    sentence: {q.sentence[:SNIPPET_CHARS]}"]
        lines += [
            f"    candidate {cid}: {label}: {definition}"
            for cid, label, definition, _ in q.candidates
        ]
        blocks.append("\n".join(lines))
    return "\n".join(blocks)


# ---------------------------------------------------------------- batching


async def _run_batches[T](
    items: Sequence[Any],
    batch_size: int,
    call: Callable[[Sequence[Any]], Awaitable[dict[int, T]]],
    concurrency: int = CONCURRENCY,
) -> dict[int, T]:
    """Run `call` over batches (global index → result), re-asking once for skipped items."""
    sem = asyncio.Semaphore(concurrency)

    async def one(indices: list[int]) -> dict[int, T]:
        async with sem:
            local = await call([items[i] for i in indices])
        return {indices[k]: v for k, v in local.items() if 0 <= k < len(indices)}

    async def sweep(indices: list[int]) -> dict[int, T]:
        batches = [indices[s : s + batch_size] for s in range(0, len(indices), batch_size)]
        merged: dict[int, T] = {}
        for part in await asyncio.gather(*(one(b) for b in batches)):
            merged |= part
        return merged

    results = await sweep(list(range(len(items))))
    missing = [i for i in range(len(items)) if i not in results]
    if missing:
        results |= await sweep(missing)
    return results


async def check_merges(
    pairs: Sequence[tuple[Entry, Entry]], runner: Runner, ledger: list[llm.CallMeta]
) -> dict[int, bool]:
    async def call(batch: Sequence[tuple[Entry, Entry]]) -> dict[int, bool]:
        res = await runner(
            "link_merge", MergeDecisions, {"pair_count": len(batch), "pairs": render_pairs(batch)}
        )
        ledger.append(res.meta)
        return {d.pair: d.same for d in res.output.decisions}

    return await _run_batches(pairs, 20, call)


async def define_concepts(
    entries: Sequence[Entry], runner: Runner, ledger: list[llm.CallMeta]
) -> dict[int, ConceptInfo]:
    async def call(batch: Sequence[Entry]) -> dict[int, ConceptInfo]:
        res = await runner(
            "concept_define",
            ConceptInfos,
            {"concept_count": len(batch), "concepts": render_entries(batch)},
        )
        ledger.append(res.meta)
        return {c.id: c for c in res.output.concepts}

    return await _run_batches(entries, 25, call)


async def propose_prereqs(
    requests: Sequence[PrereqRequest], runner: Runner, ledger: list[llm.CallMeta]
) -> dict[int, list[Prereq]]:
    async def call(batch: Sequence[PrereqRequest]) -> dict[int, list[Prereq]]:
        res = await runner(
            "concept_prereqs",
            PrereqBatch,
            {"concept_count": len(batch), "concepts": render_prereq_requests(batch)},
        )
        ledger.append(res.meta)
        out = {}
        for c in res.output.concepts:
            if 0 <= c.concept < len(batch):
                allowed = {cid for cid, _ in batch[c.concept].candidates}
                out[c.concept] = [
                    Prereq(p.id, p.confidence) for p in c.prerequisites if p.id in allowed
                ]
        return out

    return await _run_batches(requests, 15, call)


async def confirm_wikipedia(
    items: Sequence[WikiCandidate], runner: Runner, ledger: list[llm.CallMeta]
) -> dict[int, bool]:
    async def call(batch: Sequence[WikiCandidate]) -> dict[int, bool]:
        res = await runner(
            "concept_wikidata", WikiMatches, {"item_count": len(batch), "items": render_wiki(batch)}
        )
        ledger.append(res.meta)
        return {m.id: m.same for m in res.output.matches}

    return await _run_batches(items, 20, call)


async def confirm_links(
    questions: Sequence[LinkQuestion], runner: Runner, ledger: list[llm.CallMeta]
) -> dict[int, str | None]:
    """Index -> chosen candidate id or None. Ids outside a mention's candidates become None."""

    async def call(batch: Sequence[LinkQuestion]) -> dict[int, str | None]:
        res = await runner(
            "link_confirm",
            LinkAnswers,
            {"mention_count": len(batch), "mentions": render_link_questions(batch)},
        )
        ledger.append(res.meta)
        out: dict[int, str | None] = {}
        for a in res.output.answers:
            if 0 <= a.mention < len(batch):
                allowed = {cid for cid, *_ in batch[a.mention].candidates}
                out[a.mention] = a.concept_id if a.concept_id in allowed else None
        return out

    return await _run_batches(questions, LINK_BATCH, call, LINK_CONCURRENCY)
