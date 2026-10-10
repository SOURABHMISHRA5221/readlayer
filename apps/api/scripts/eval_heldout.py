"""Held-out linker evaluation: fresh articles the graph was not built from (M2.1).

Run:  cd apps/api && uv run python -m scripts.eval_heldout [--collect]

--collect picks HELDOUT_PER_SOURCE fresh articles per news source from the same feeds as the
corpus, skipping every URL in data/corpus_urls.txt, and writes data/heldout_urls.txt (the
held-out marker: build_concepts refuses any overlap with the corpus and never builds from these).
Then each article goes through the production ingest path (extract demands, link against the
current data/concepts.json at the calibrated LINK_THRESHOLD) and the report covers those
articles only. Spend is the change in today's spend counter, so it includes every call.
"""

import argparse
import asyncio
import os
import random
import sys
from collections import Counter
from datetime import UTC, datetime
from functools import partial

import numpy as np

from app import llm
from app.config import get_settings
from app.content.summary import article_domain
from app.graph.graph import ConceptGraph
from app.graph.linking import EMBED_TYPES, alias_target, sentence_around
from app.graph.loader import set_graph
from app.graph.models import ConceptGraphFile
from app.ingest.models import USER_INGESTED, ContentDoc
from app.ingest.safe_fetch import FetchError, SafeFetcher
from app.ingest.urls import normalize_url, url_hash
from app.log import configure_logging
from app.store.content_repo import get_content_store
from scripts.apply_overrides import calibrated_floor
from scripts.build_cache import BuildCache
from scripts.build_concepts import CACHE_DIR, CONCEPTS_FILE, HELDOUT_FILE, corpus_sources
from scripts.collect_corpus import SOURCES, Source, collect_source
from scripts.ingest_corpus import DATA_DIR, CorpusEntry, append_state, parse_corpus, run

HELDOUT_PER_SOURCE = 3
HELDOUT_TARGET = 15
HELDOUT_FULL = 30  # M2.2: the 15 business articles plus 15 non-business ones
STATE_FILE = DATA_DIR / "heldout_state.jsonl"
REPORT_FILE = DATA_DIR / "heldout_report.md"
COST_LIMIT_USD = 1.0
SEED = 5


async def collect() -> list[CorpusEntry]:
    if HELDOUT_FILE.exists() and len(read_heldout()) > HELDOUT_TARGET:
        raise SystemExit("held-out list is frozen at 30; --collect would overwrite it")
    corpus = set(corpus_sources())
    fetcher = SafeFetcher()
    results = await asyncio.gather(*(collect_source(fetcher, s) for s in SOURCES))
    fresh: dict[str, list[CorpusEntry]] = {}
    for r in results:
        if r.skipped:
            print(f"{r.source.tag}: skipped ({r.skipped})")
            continue
        items = [i for i in r.items if normalize_url(i.url) not in corpus]
        fresh[r.source.tag] = [CorpusEntry(i.url, i.source) for i in items]
    # HELDOUT_PER_SOURCE each, then round-robin top-up if a source was skipped or short
    picked = [e for entries in fresh.values() for e in entries[:HELDOUT_PER_SOURCE]]
    rank = HELDOUT_PER_SOURCE
    while len(picked) < HELDOUT_TARGET and any(len(v) > rank for v in fresh.values()):
        picked += [v[rank] for v in fresh.values() if len(v) > rank]
        rank += 1
    picked = picked[:HELDOUT_TARGET]
    print(
        "held-out picks: "
        + ", ".join(f"{s} {n}" for s, n in Counter(e.source for e in picked).items())
    )
    header = (
        "# ReadLayer held-out linker evaluation set (M2.1). NEVER add these to the corpus;\n"
        "# build_concepts refuses any overlap. format: url<TAB>source\n"
    )
    HELDOUT_FILE.write_text(
        header + "".join(f"{e.url}\t{e.source}\n" for e in picked), encoding="utf-8"
    )
    return picked


# ---------------------------------------------------------------- M2.2: non-business held-out

# Section feeds per taxonomy domain (plan §E.1) and how many articles each domain gets.
OPEN_SPREAD: dict[str, int] = {
    "technology": 2, "science": 2, "health": 2, "sports": 2, "environment": 2,
    "politics": 2, "law": 1, "culture": 1, "education": 1,
}  # fmt: skip
_BBC = "https://feeds.bbci.co.uk/news/{}/rss.xml"
_GUARDIAN = "https://www.theguardian.com/{}/rss"
OPEN_SOURCES: dict[str, tuple[Source, ...]] = {
    "technology": (
        Source("bbc", (_BBC.format("technology"),), ("/news/articles/",)),
        Source("guardian", (_GUARDIAN.format("technology"),), ("/technology/",)),
    ),
    "science": (
        Source("bbc", (_BBC.format("science_and_environment"),), ("/news/articles/",)),
        Source("guardian", (_GUARDIAN.format("science"),), ("/science/",)),
    ),
    "health": (
        Source("bbc", (_BBC.format("health"),), ("/news/articles/",)),
        Source("guardian", (_GUARDIAN.format("society/health"),), ("/society/",)),
    ),
    "sports": (
        Source("bbc", ("https://feeds.bbci.co.uk/sport/rss.xml",), ("/sport/",)),
        Source("guardian", (_GUARDIAN.format("sport"),), ("/sport/", "/football/")),
    ),
    "environment": (
        Source("guardian", (_GUARDIAN.format("environment"),), ("/environment/",)),
        Source("bbc", (_BBC.format("science_and_environment"),), ("/news/articles/",)),
    ),
    "politics": (
        Source("bbc", (_BBC.format("politics"),), ("/news/articles/",)),
        Source("guardian", (_GUARDIAN.format("politics"),), ("/politics/",)),
    ),
    "law": (Source("guardian", (_GUARDIAN.format("law"),), ("/law/",)),),
    "culture": (
        Source("guardian", (_GUARDIAN.format("culture"),), ("/culture/", "/books/", "/music/",
                                                             "/film/", "/artanddesign/")),
        Source("bbc", (_BBC.format("entertainment_and_arts"),), ("/news/articles/",)),
    ),
    "education": (
        Source("guardian", (_GUARDIAN.format("education"),), ("/education/",)),
        Source("thehindu", ("https://www.thehindu.com/education/feeder/default.rss",),
               ("/education/",)),
    ),
}  # fmt: skip
OPEN_MIN_WORDS = 400
OPEN_PUBLISHED_AFTER = "2026-10-01"
OPEN_HEADER = (
    "# ReadLayer held-out linker evaluation set. NEVER add these to the corpus; build_concepts\n"
    "# refuses any overlap. format: url<TAB>source<TAB>domain. Lines 1–15: M2.1 (business);\n"
    "# 16–30: M2.2 non-business, appended by --collect-open. Domains fixed before measuring.\n"
)


def read_heldout() -> list[CorpusEntry]:
    return parse_corpus(HELDOUT_FILE.read_text(encoding="utf-8").splitlines())


def write_heldout(entries: list[CorpusEntry]) -> None:
    lines = "".join(f"{e.url}\t{e.source}\t{e.domain}\n" for e in entries)
    HELDOUT_FILE.write_text(OPEN_HEADER + lines, encoding="utf-8")


async def _long_enough(fetcher: SafeFetcher, url: str) -> bool:
    from app.ingest.extract import extract

    try:
        page = await fetcher.fetch(url)
    except FetchError:
        return False
    html = page.body.decode(page.encoding, errors="replace") if page.encoding else page.body
    extracted = await asyncio.to_thread(extract, html, page.url)
    return sum(len(p.split()) for p in extracted.paragraphs) >= OPEN_MIN_WORDS


async def collect_open(graph: ConceptGraph) -> list[CorpusEntry]:
    """Append 15 non-business articles (OPEN_SPREAD) to the 15 business ones. The first 15
    keep their url and source; they gain their domain (the dominant one among their linked
    concepts on the current graph). No ingest, no LLM: only feeds, fetch and extraction."""
    old = read_heldout()
    if len(old) != HELDOUT_TARGET:
        raise SystemExit(f"expected {HELDOUT_TARGET} held-out lines, found {len(old)}")
    content = get_content_store()
    labelled = []
    for e in old:
        doc = await content.get(url_hash(e.url))
        domain = (article_domain(doc, graph) if doc else None) or "business"
        labelled.append(CorpusEntry(e.url, e.source, e.domain or domain))
    taken = set(corpus_sources()) | {normalize_url(e.url) for e in old}
    fetcher = SafeFetcher()
    cutoff = datetime.fromisoformat(OPEN_PUBLISHED_AFTER).replace(tzinfo=UTC).timestamp()
    picked: list[CorpusEntry] = []
    for domain, want in OPEN_SPREAD.items():
        got: list[CorpusEntry] = []
        for source in OPEN_SOURCES[domain]:
            if len(got) >= want:
                break
            result = await collect_source(fetcher, source)
            if result.skipped:
                print(f"{domain}/{source.tag}: skipped ({result.skipped})")
                continue
            for item in result.items:
                if len(got) >= want:
                    break
                key = normalize_url(item.url)
                if key in taken or item.published < cutoff or "/wiki/" in key:
                    continue
                if not await _long_enough(fetcher, item.url):
                    continue
                taken.add(key)
                got.append(CorpusEntry(item.url, source.tag, domain))
        if len(got) < want:
            raise SystemExit(f"{domain}: found {len(got)} of {want} eligible articles")
        picked += got
        print(f"{domain}: " + ", ".join(f"{e.source} {e.url}" for e in got))
    write_heldout(labelled + picked)
    return labelled + picked


def method(graph: ConceptGraph, d) -> str:
    if d.target_id is None:
        return "unlinked"
    return "alias" if alias_target(graph, d) == d.target_id else "confirmed"


def _cos(a, b) -> float:
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)))


async def report(
    graph: ConceptGraph,
    docs: list[ContentDoc],
    sources: dict[str, str],
    cache: BuildCache,
    floor: float,
    cost: float,
) -> str:
    rows: dict[str, Counter[str]] = {}
    confirmed, unlinked = [], Counter()
    for doc in docs:
        src = sources[doc.content_id]
        texts = {p.id: p.text for p in doc.paragraphs}
        for d in doc.demands:
            if d.type not in EMBED_TYPES:
                continue
            m = method(graph, d)
            rows.setdefault(src, Counter())[m] += 1
            rows.setdefault("ALL", Counter())[m] += 1
            if m == "confirmed":
                sentence = sentence_around(texts.get(d.paragraph_id, ""), d.anchor.exact)
                confirmed.append((d, sentence))
            elif m == "unlinked":
                unlinked[d.label] += 1
    labels = sorted({d.label for d, _ in confirmed} | set(unlinked))
    vecs = dict(zip(labels, await cache.embed(labels, "SEMANTIC_SIMILARITY"), strict=True))

    out = [
        "# Held-out linker evaluation (M2.1)",
        "",
        f"{len(docs)} fresh articles from the corpus feeds, none in data/corpus_urls.txt and "
        f"never used to build the graph. Graph version {graph.version}, {len(graph)} concepts, "
        f"LINK_THRESHOLD {floor}. **This is the coverage number to quote**; in-corpus coverage "
        "in m2_report.md is inflated because single-doc concepts were built from those same "
        "mentions.",
        "",
        "| source | concept/term demands | exact-name | model-confirmed | unlinked |",
        "|---|---|---|---|---|",
    ]
    for src in [*sorted(s for s in rows if s != "ALL"), "ALL"]:
        c = rows[src]
        n = sum(c.values()) or 1
        cells = [f"{c[k]} ({c[k] / n:.0%})" for k in ("alias", "confirmed", "unlinked")]
        out.append(f"| {src} | {sum(c.values())} | " + " | ".join(cells) + " |")

    rng = random.Random(SEED)
    out += ["", "## 10 model-confirmed links to spot-check", ""]
    for i, (d, sentence) in enumerate(rng.sample(confirmed, min(10, len(confirmed))), 1):
        concept = graph.get(d.target_id)
        score = _cos(vecs[d.label], graph.vector(concept.id))
        out.append(
            f'{i}. "{d.anchor.exact}" → **{concept.label}** (cos {score:.3f})\n'
            f"   context: {sentence[:220]}"
        )
    out += ["", "## 5 unlinked labels with their nearest concept", ""]
    top = [label for label, _ in unlinked.most_common()]
    for label in top[:5]:
        concept, score = graph.nearest(vecs[label], 1)[0]
        gate = "below floor, model not asked" if score < floor else "model said none"
        out.append(
            f"- {label} (×{unlinked[label]}) → nearest **{concept.label}**, "
            f"cos {score:.3f} ({gate})"
        )
    out += ["", f"Cost of this evaluation: **${cost:.3f}** (limit ${COST_LIMIT_USD:.2f})"]
    return "\n".join(out) + "\n"


async def main(args: argparse.Namespace) -> int:
    configure_logging("WARNING")
    floor = calibrated_floor()
    os.environ["LINK_THRESHOLD"] = str(floor)  # ingest links at the calibrated floor
    get_settings.cache_clear()
    graph = ConceptGraph(ConceptGraphFile.model_validate_json(CONCEPTS_FILE.read_bytes()))
    set_graph(graph)
    store = llm.get_spend_store()
    spent_before = await store.get_today()

    if args.collect_open:
        entries = await collect_open(graph)
        print(f"wrote {len(entries)} held-out lines to {HELDOUT_FILE}; nothing ingested")
        return 0
    if args.collect or not HELDOUT_FILE.exists():
        entries = await collect()
    else:
        entries = parse_corpus(HELDOUT_FILE.read_text(encoding="utf-8").splitlines())
    print(f"{len(entries)} held-out articles")
    outcomes, budget_hit = await run(entries, record=partial(append_state, path=STATE_FILE))
    if budget_hit:
        print("STOPPED: daily LLM budget reached")
        return 2
    failed = [o for o in outcomes if o.status == "failed"]
    print(f"ingested {len(outcomes) - len(failed)}, failed {len(failed)}")

    sources = {url_hash(e.url): e.source for e in entries}
    content = get_content_store()
    docs = [
        d
        for cid in sources
        if (d := await content.get(cid)) is not None and d.source != USER_INGESTED
    ]
    cache = BuildCache(CACHE_DIR, get_settings())
    cost = await store.get_today() - spent_before
    text = await report(graph, docs, sources, cache, floor, cost + cache.embed_cost_new)
    REPORT_FILE.write_text(text, encoding="utf-8")
    print(text)
    return 0 if cost <= COST_LIMIT_USD else 3


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--collect", action="store_true", help="re-pick the held-out articles")
    parser.add_argument(
        "--collect-open",
        action="store_true",
        help="M2.2: append 15 non-business articles (no ingest, no LLM)",
    )
    sys.exit(asyncio.run(main(parser.parse_args())))
