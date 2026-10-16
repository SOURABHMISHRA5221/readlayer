"""Warm the web lookups behind the note card's Up next chips (decision 67 N4).

    uv run python -m scripts.warm_next_up --dry-run   # key ideas, cache misses, provider calls
    uv run python -m scripts.warm_next_up --write     # fetch the misses (Sourabh's yes)

Docs: warm_demo's DEMO_ARTICLES and the 16 pre-ingested first-page articles (as relink_senses).
Per doc, the chips search the article's first WEB_TRIGGERS key ideas in every configured format,
through the same per-(concept, format) cache the API uses. Tavily serves article and podcast,
YouTube video (2 calls each). **Stop rule:** more than TAVILY_STOP Tavily calls → only the demo
articles are warmed. Production writes: the `rec_cache` entries the dry run counts.
"""

import argparse
import asyncio
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass

from app.graph.graph import ConceptGraph
from app.ingest.models import ContentDoc
from app.recs.feed_rank import key_ideas
from app.recs.models import FORMATS, Format
from app.recs.router import WEB_TRIGGERS
from app.recs.web_search import build_query

TAVILY_STOP = 150
PROVIDER: Mapping[Format, str] = {"article": "tavily", "podcast": "tavily", "video": "youtube"}
CALLS: Mapping[str, int] = {"tavily": 1, "youtube": 2}


@dataclass(frozen=True)
class Miss:
    content_id: str
    concept_id: str
    label: str
    domain: str
    fmt: Format


async def plan_misses(
    docs: Mapping[str, ContentDoc],
    graph: ConceptGraph,
    formats: Iterable[Format],
    cached: Callable[[str, Format, str], Awaitable[bool]],
) -> list[Miss]:
    """Every (key idea, format) the chips would search whose cache entry is missing or stale;
    a concept shared by two docs is searched once. `cached(concept, fmt, query)` → fresh?"""
    out: list[Miss] = []
    seen: set[tuple[str, Format]] = set()
    fmts = [f for f in FORMATS if f in set(formats)]
    for cid, doc in docs.items():
        ideas, _ = key_ideas(doc, graph)
        for c in ideas[:WEB_TRIGGERS]:
            for fmt in fmts:
                if (c.id, fmt) in seen:
                    continue
                seen.add((c.id, fmt))
                if not await cached(c.id, fmt, build_query(c.label, fmt, c.domain)):
                    out.append(Miss(cid, c.id, c.label, c.domain, fmt))
    return out


def provider_calls(misses: Iterable[Miss]) -> dict[str, int]:
    calls = {"tavily": 0, "youtube": 0}
    for m in misses:
        p = PROVIDER[m.fmt]
        calls[p] += CALLS[p]
    return calls


async def main_async(write: bool) -> int:
    from app.graph.loader import get_graph
    from app.recs.web_search import get_web_search
    from app.store.content_repo import get_content_store
    from scripts.relink_senses import demo_doc_ids
    from scripts.warm_demo import DEMO_ARTICLES

    ids = await demo_doc_ids()  # loads the serving graph
    graph = get_graph()
    if "+g" not in graph.version:
        raise SystemExit(f"grown concepts did not load (graph {graph.version}); stopping")
    store = get_content_store()
    docs = {cid: d for cid in ids if (d := await store.get(cid)) is not None}
    web = get_web_search()

    async def fresh(concept_id: str, fmt: Format, query: str) -> bool:
        return (await web.cached(concept_id, fmt, query))[1]

    misses = await plan_misses(docs, graph, web.formats, fresh)
    calls = provider_calls(misses)
    for m in misses:
        print(f"  {m.content_id[:8]} {m.fmt:8s} {m.label} ({m.domain})")
    print(f"{len(docs)} docs, {len(misses)} cache misses; youtube {calls['youtube']} calls")
    print(f"tavily {calls['tavily']} calls (stop rule: > {TAVILY_STOP} → demo articles only)")
    if calls["tavily"] > TAVILY_STOP:
        demo = set(DEMO_ARTICLES)
        misses = [m for m in misses if m.content_id in demo]
        print(f"stop rule: warming the demo articles only, {len(misses)} misses, "
              f"tavily {provider_calls(misses)['tavily']}")  # fmt: skip
    if not write:
        print("dry run: nothing fetched")
        return 0
    filled = 0
    for m in misses:
        results = await web.fetch(m.concept_id, m.label, m.fmt, m.domain)
        filled += bool(results)
    print(f"fetched {len(misses)} lookups, {filled} with results")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--write", action="store_true")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main_async(args.write)))


if __name__ == "__main__":
    main()
