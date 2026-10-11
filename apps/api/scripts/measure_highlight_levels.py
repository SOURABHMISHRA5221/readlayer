"""Design pass A1: how often a shown span is a "refresher" (reader understands it) vs "new".

    cd apps/api && uv run python -m scripts.measure_highlight_levels [--density balanced]

Read-only: the concept graph (CONCEPTS_URI) and the corpus docs from the content store; demo
persona states are built locally from their specs. No LLM, no writes.
"""

import argparse
import asyncio
from collections import Counter
from datetime import UTC, datetime

from app.config import get_settings
from app.graph.loader import load_graph
from app.ingest.models import is_corpus
from app.reader.personas import PERSONAS, build_template
from app.reader.state import ReaderState
from app.scoring import scorer
from app.store.content_repo import get_content_store
from scripts.warm_demo import DEMO_ARTICLES


async def main(density: str) -> None:
    graph = await load_graph(get_settings().concepts_uri)
    docs = [d async for d in get_content_store().iter_all() if is_corpus(d)]
    now = datetime.now(UTC)
    print(f"{len(docs)} corpus docs, graph {graph.version}, density {density}")
    for key, spec in PERSONAS.items():
        t = build_template(key, spec, graph, now)
        state = ReaderState(theta=dict(t.theta), edges=dict(t.edges))
        levels: Counter[str] = Counter()
        demo: dict[str, Counter[str]] = {}
        for d in docs:
            spans = scorer.annotate(d, graph, state, density, now).spans
            got = Counter(s.level for s in spans)
            levels.update(got)
            if d.content_id in DEMO_ARTICLES:
                demo[d.content_id[:8]] = got
        total = sum(levels.values()) or 1
        print(f"{key:15s} spans {total:5d}  refresher {levels['refresher']:4d} "
              f"({levels['refresher'] / total:.1%})  demo articles {dict(demo)}")  # fmt: skip


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--density", default="balanced", choices=["minimal", "balanced", "guided"])
    asyncio.run(main(parser.parse_args().density))
