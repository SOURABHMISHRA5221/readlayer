"""Ingestion pipeline: cache check → fetch/extract → features → demands → store.

Ingestion happens once per URL and is shared by every reader. A cache hit makes no fetch and no
LLM call, which is also how already-ingested content stays available when the LLM budget is spent.
"""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Literal

from app.config import get_settings
from app.graph.linking import link_demands
from app.graph.loader import get_graph
from app.ingest import safe_fetch as fetch
from app.ingest.demands import extract_demands
from app.ingest.extract import Metadata, build_paragraphs, clean_paragraphs, extract
from app.ingest.features import parse_structure, structure
from app.ingest.models import ContentDoc, StoredParagraph
from app.ingest.urls import normalize_url, url_hash
from app.store.content_repo import get_content_store

log = logging.getLogger("app.ingest")

MIN_ARTICLE_WORDS = 80  # below this it's a paywall stub, a gallery or a failed extraction


async def ingest_url(url: str) -> ContentDoc:
    fetch.validate_url(url)
    content_id = url_hash(url)
    if cached := await _cached(content_id):
        return cached
    page = await fetch.safe_fetch(url)
    html = page.body.decode(page.encoding, errors="replace") if page.encoding else page.body
    extracted = await asyncio.to_thread(extract, html, page.url)
    title = extracted.title or extracted.site or page.url
    return await _build(
        content_id,
        url,
        page.url,
        title,
        extracted.site,
        extracted.paragraphs,
        "fetch",
        extracted.metadata,
    )


async def ingest_submitted(url: str, title: str, paragraphs: list[str]) -> ContentDoc:
    """Extension shape: text already extracted (and redacted) client-side."""
    host = fetch.validate_url(url).host
    content_id = url_hash(url)
    if cached := await _cached(content_id):
        return cached
    texts = clean_paragraphs(paragraphs)
    return await _build(content_id, url, url, title.strip() or host, host, texts, "extension")


async def _cached(content_id: str) -> ContentDoc | None:
    doc = await get_content_store().get(content_id)
    if doc is not None:
        log.info("content cache hit", extra={"content_id": content_id})
    return doc


async def _build(
    content_id: str,
    url: str,
    final_url: str,
    title: str,
    site: str,
    texts: list[str],
    source: Literal["fetch", "extension"],
    metadata: Metadata | None = None,
) -> ContentDoc:
    if sum(len(t.split()) for t in texts) < MIN_ARTICLE_WORDS:
        raise fetch.FetchError(
            "no_article_text",
            "no readable article text found (the page may be paywalled or not an article)",
        )
    paragraphs = build_paragraphs(texts)
    parse_scores = await asyncio.to_thread(lambda: [parse_structure(p.text) for p in paragraphs])
    result = await extract_demands(paragraphs)
    demands, _ = await link_demands(
        get_graph(),
        result.demands,
        {p.id: p.text for p in paragraphs},
        get_settings().link_threshold,
    )
    doc = ContentDoc(
        content_id=content_id,
        url=normalize_url(url),
        final_url=final_url,
        title=title[:300],
        site=site[:120],
        source=source,
        fetched_at=datetime.now(UTC).isoformat(),
        description=metadata.description if metadata else None,
        author=metadata.author if metadata else None,
        published=metadata.published if metadata else None,
        image=metadata.image if metadata else None,
        paragraphs=[
            StoredParagraph(
                id=p.id, text=p.text, structure=structure(score, result.dense.get(p.id, False))
            )
            for p, score in zip(paragraphs, parse_scores, strict=True)
        ],
        demands=demands,
        demands_dropped=result.dropped,
        llm_calls=result.calls,
    )
    await get_content_store().put(doc)
    log.info(
        "content ingested",
        extra={
            "content_id": content_id,
            "source": source,
            "paragraphs": len(paragraphs),
            "demands": len(demands),
            "demands_linked": sum(d.target_id is not None for d in demands),
            "demands_dropped": result.dropped,
            "cost_usd": round(sum(c.cost_usd for c in result.calls), 6),
            "models": sorted({c.model for c in result.calls}),
        },
    )
    return doc
