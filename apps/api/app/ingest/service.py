"""Ingestion pipeline: cache check → fetch/extract (phase 1) → features, demands, linking,
store (phase 2).

Ingestion happens once per URL and is shared by every reader. A cache hit makes no fetch and no
LLM call, which is also how already-ingested content stays available when the LLM budget is spent.

The two phases are separate so "Open here" can show the article as soon as it is extracted:
phase 1 stores a `pending_contents/` doc and returns; phase 2 runs in its own request under a
lease (`analyse_pending`). Both are ordinary requests, so nothing runs after a response (Cloud
Run throttles CPU then). The synchronous paths (POST /v1/content, the corpus scripts) run both
phases back to back through the same pending doc and lease.
"""

import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from app import llm, warm
from app.config import get_settings
from app.graph.heldout import is_heldout
from app.graph.linking import link_demands
from app.graph.loader import get_graph
from app.ingest import safe_fetch as fetch
from app.ingest.demands import extract_demands
from app.ingest.extract import (
    Metadata,
    Paragraph,
    build_paragraphs,
    clean_paragraphs,
    extract,
)
from app.ingest.features import parse_structure, structure
from app.ingest.growing import GrowthResult, Reserver, run_growth
from app.ingest.models import (
    ContentDoc,
    Demand,
    LLMCall,
    PendingDoc,
    PendingParagraph,
    Source,
    StoredParagraph,
)
from app.ingest.urls import normalize_url, url_hash
from app.store.content_repo import get_content_store
from app.store.pending_repo import (
    PENDING_TTL,
    AnalysisBusy,
    AnalysisFailed,
    ContentTranscribing,
    NotPending,
    get_pending_repo,
)

if TYPE_CHECKING:
    from app.privacy.pii import Findings

log = logging.getLogger("app.ingest")

MIN_ARTICLE_WORDS = 80  # below this it's a paywall stub, a gallery or a failed extraction
LEASE_MARGIN = timedelta(seconds=30)


async def ingest_url(
    url: str, source: Source = "fetch", reserve: Reserver | None = None
) -> ContentDoc:
    """Fetch, extract and analyse a URL once. A cached doc keeps the source it was made with.
    `reserve`: the reader's concept-growth slots, taken in phase 2 (the corpus scripts pass
    none)."""
    fetch.validate_url(url)
    content_id = url_hash(url)
    if cached := await _cached(content_id):
        return cached
    if await get_pending_repo().get(content_id) is None:
        await fetch_and_extract(url, source)
    return await analyse_pending(content_id, reserve)


def clean_submitted(paragraphs: list[str]) -> list[str]:
    """Extension text, cleaned like fetched text. The PII backstop scans this; the strict
    redactor then runs over it before anything is stored (router, DESIGN §11.3)."""
    return clean_paragraphs(paragraphs)


async def pii_check(paragraphs: list[str]) -> "Findings":
    """The Presidio backstop (M8 §A3), off the event loop: spaCy is CPU-bound."""
    from app.privacy import pii

    return await asyncio.to_thread(pii.check, paragraphs)


async def store_submitted(content_id: str, url: str, title: str, texts: list[str]) -> PendingDoc:
    """Phase 1 for extension text (no fetch, no LLM): the pending doc under its `ext:` id, or the
    one another request stored first."""
    host = fetch.validate_url(url).host
    warm.start()  # notes follow: load LiteLLM and spaCy now, off the reader's wait (decision 69)
    return await _store_pending(
        content_id, url, normalize_url(url), title.strip() or host, host, texts, "extension"
    )  # fmt: skip


async def fetch_and_extract(url: str, source: Source = "fetch") -> PendingDoc:
    """Phase 1: safe_fetch, extraction and paragraph ids; no LLM call. Stores the pending doc
    (or returns the one another request stored first)."""
    fetch.validate_url(url)
    warm.start()  # overlaps the fetch; analysis waits for it (decision 69)
    started = time.perf_counter()
    page = await fetch.safe_fetch(url)
    fetched = time.perf_counter()
    html = page.body.decode(page.encoding, errors="replace") if page.encoding else page.body
    extracted = await asyncio.to_thread(extract, html, page.url)
    log.info(
        "phase 1 timing",
        extra={
            "fetch_ms": round((fetched - started) * 1000),
            "extract_ms": round((time.perf_counter() - fetched) * 1000),  # incl. first import
        },
    )
    title = extracted.title or extracted.site or page.url
    return await _store_pending(
        url_hash(url),
        url,
        page.url,
        title,
        extracted.site,
        extracted.paragraphs,
        source,
        extracted.metadata,
    )


async def analyse_pending(content_id: str, reserve: Reserver | None = None) -> ContentDoc:
    """Phase 2 under the lease. Budget refusals release the lease without counting an attempt
    (nothing ran); any other failure, including the timeout, counts one. `reserve`: the
    requesting reader's growth slots (M9 part 1); None for scripts and the corpus."""
    if cached := await _cached(content_id):
        return cached
    await warm.ready()  # usually done during phase 1; a new instance waits here, off the loop
    settings = get_settings()
    repo = get_pending_repo()
    lease = timedelta(seconds=settings.analyse_timeout_s) + LEASE_MARGIN
    status, pending = await repo.acquire(content_id, datetime.now(UTC), lease)
    if status == "missing" or pending is None:
        raise NotPending(content_id)
    if status == "wrong_stage":
        raise ContentTranscribing(content_id)
    if status == "busy":
        raise AnalysisBusy(content_id)
    if status == "exhausted":
        raise AnalysisFailed(content_id)
    try:
        deadline = asyncio.get_running_loop().time() + settings.analyse_timeout_s
        async with asyncio.timeout(settings.analyse_timeout_s):
            doc = await _analyse(pending, deadline, reserve)
    except llm.BudgetExceeded:
        await repo.release(content_id, failed=False)
        raise
    except asyncio.CancelledError:  # the request went away; not the article's fault
        await asyncio.shield(repo.release(content_id, failed=False))
        raise
    except Exception:  # model errors, linking errors and the timeout (TimeoutError)
        await repo.release(content_id, failed=True)
        raise
    await repo.delete(content_id)
    return doc


async def _cached(content_id: str) -> ContentDoc | None:
    doc = await get_content_store().get(content_id)
    if doc is not None:
        log.info("content cache hit", extra={"content_id": content_id})
    return doc


async def _store_pending(
    content_id: str,
    url: str,
    final_url: str,
    title: str,
    site: str,
    texts: list[str],
    source: Source,
    metadata: Metadata | None = None,
) -> PendingDoc:
    if sum(len(t.split()) for t in texts) < MIN_ARTICLE_WORDS:
        raise fetch.FetchError(
            "no_article_text",
            "no readable article text found (the page may be paywalled or not an article)",
        )
    now = datetime.now(UTC)
    doc = PendingDoc(
        content_id=content_id,
        url=normalize_url(url),
        final_url=final_url,
        title=title[:300],
        site=site[:120],
        source=source,
        fetched_at=now.isoformat(),
        description=metadata.description if metadata else None,
        author=metadata.author if metadata else None,
        published=metadata.published if metadata else None,
        image=metadata.image if metadata else None,
        paragraphs=[PendingParagraph(id=p.id, text=p.text) for p in build_paragraphs(texts)],
        expire_at=now + PENDING_TTL,
    )
    stored = await get_pending_repo().create(doc)
    log.info(
        "content extracted",
        extra={"content_id": content_id, "source": source, "paragraphs": len(stored.paragraphs)},
    )
    return stored


def _paragraphs(pending: PendingDoc) -> list[Paragraph]:
    """The pending paragraphs as stored. build_paragraphs gave them their ids in phase 1 and is
    deterministic, so rebuilding only restores the offsets."""
    return build_paragraphs([p.text for p in pending.paragraphs])


async def _grow(
    pending: PendingDoc,
    demands: list[Demand],
    paragraphs: list[Paragraph],
    deadline: float,
    reserve: Reserver | None,
) -> GrowthResult:
    """Online concept growth for this article's unlinked demands (M2.2 §C, M9 part 1). Slots are
    reserved here, for exactly the labels growth will try, from the reader whose request runs
    phase 2 (`reserve`); scripts pass none. A pending doc stored before M9 still carries the
    slots it reserved in phase 1 and uses those. Any failure skips growth, never the ingest."""
    settings = get_settings()
    if not settings.growth_enabled or is_heldout(pending.content_id):
        return GrowthResult(demands, [], False, [])
    if pending.grow_slots > 0:
        held = pending.grow_slots

        async def take(want: int) -> int:
            return min(want, held)

    elif reserve is None:
        return GrowthResult(demands, [], False, [])
    else:
        take = reserve
    budget = min(settings.growth_timeout_s, deadline - asyncio.get_running_loop().time() - 5)
    return await run_growth(
        pending.content_id, demands, {p.id: p.text for p in paragraphs}, [], budget, take
    )


def _transcript_calls(pending: PendingDoc) -> list[LLMCall]:
    """A recording's transcribe calls, as one entry (every window, retry and re-ask summed)."""
    record = pending.media.transcript if pending.media else None
    if record is None:
        return []
    return [
        LLMCall(
            task="transcribe",
            model=record.model,
            prompt_version=record.prompt_version,
            tokens_in=record.tokens_in,
            tokens_out=record.tokens_out,
            cost_usd=record.cost_usd,
            fell_back=False,
        )
    ]


async def _analyse(
    pending: PendingDoc, deadline: float = float("inf"), reserve: Reserver | None = None
) -> ContentDoc:
    paragraphs = _paragraphs(pending)
    t0 = time.perf_counter()
    parse_scores = await asyncio.to_thread(lambda: [parse_structure(p.text) for p in paragraphs])
    t1 = time.perf_counter()
    result = await extract_demands(paragraphs)
    t2 = time.perf_counter()
    demands, _ = await link_demands(
        get_graph(),
        result.demands,
        {p.id: p.text for p in paragraphs},
        get_settings().link_threshold,
        site=pending.site,
        url=pending.final_url,
    )
    t3 = time.perf_counter()
    grown = await _grow(pending, demands, paragraphs, deadline, reserve)
    t4 = time.perf_counter()
    demands = grown.demands
    doc = ContentDoc(
        content_id=pending.content_id,
        url=pending.url,
        final_url=pending.final_url,
        title=pending.title,
        site=pending.site,
        source=pending.source,
        fetched_at=pending.fetched_at,
        description=pending.description,
        author=pending.author,
        published=pending.published,
        image=pending.image,
        paragraphs=[
            StoredParagraph(
                id=p.id,
                text=p.text,
                structure=structure(score, result.dense.get(p.id, False)),
                start_s=stored.start_s,
            )
            for p, score, stored in zip(paragraphs, parse_scores, pending.paragraphs, strict=True)
        ],
        demands=demands,
        demands_dropped=result.dropped,
        llm_calls=[*_transcript_calls(pending), *result.calls, *grown.calls],
        media=pending.media,
        grow_pending=grown.pending,
        grow_tried=grown.tried,
    )
    await get_content_store().put(doc)
    log.info(
        "content ingested",
        extra={
            "content_id": pending.content_id,
            "source": pending.source,
            "paragraphs": len(paragraphs),
            "demands": len(demands),
            "demands_linked": sum(d.target_id is not None for d in demands),
            "demands_dropped": result.dropped,
            "cost_usd": round(sum(c.cost_usd for c in result.calls), 6),
            "models": sorted({c.model for c in result.calls}),
            # Stage times, to find where a slow first analysis waits (decision 69 C).
            "parse_ms": round((t1 - t0) * 1000),
            "extract_ms": round((t2 - t1) * 1000),
            "link_ms": round((t3 - t2) * 1000),
            "grow_ms": round((t4 - t3) * 1000),
        },
    )
    return doc
