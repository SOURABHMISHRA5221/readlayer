"""Seed the demo personas' read-only reader-graph templates (DESIGN §4, decision 7).

Builds each persona's template from its spec (app/reader/personas.py) against the concept graph
the API serves (CONCEPTS_URI, or --graph for a local file) and prints per-persona stats and
document sizes. With --write it stores them at Firestore `persona_templates/{persona}`; running
API instances pick a new template up on restart. Demo readers who already have a copy keep it.

Run:  cd apps/api && uv run python -m scripts.seed_personas [--graph ../../data/concepts.json]
      [--write]
"""

import argparse
import asyncio
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from app.config import get_settings
from app.graph.graph import ConceptGraph
from app.graph.loader import load_graph
from app.graph.models import ConceptGraphFile
from app.log import configure_logging
from app.reader.personas import PERSONAS, build_template
from app.store.docstore import Doc, Txn, get_doc_store
from app.store.persona_repo import template_path, template_to_doc
from app.store.reader_repo import FIRESTORE_DOC_LIMIT, firestore_size


def _local_graph(path: str) -> ConceptGraph:
    return ConceptGraph(ConceptGraphFile.model_validate_json(Path(path).read_bytes()))


async def _graph(path: str | None) -> ConceptGraph:
    if path:
        return _local_graph(path)
    return await load_graph(get_settings().concepts_uri)


async def main(args: argparse.Namespace) -> int:
    configure_logging("WARNING")
    graph = await _graph(args.graph)
    if len(graph) == 0:
        print("no concept graph: set CONCEPTS_URI or pass --graph", file=sys.stderr)
        return 1
    now = datetime.now(UTC)
    docs: dict[str, Doc] = {}
    print(f"graph {graph.version}: {len(graph)} concepts")
    for key, spec in PERSONAS.items():
        template = build_template(key, spec, graph, now)
        doc = template_to_doc(template, graph, now)
        size = len(template_path(key).encode()) + 16 + firestore_size(doc)
        bands = Counter(e.band for e in template.edges.values())
        domains = Counter(graph.get(c).domain for c in template.edges if graph.get(c))
        print(
            f"{key:15} {len(template.edges):4} edges  {size / 1024:6.1f} KB "
            f"({100 * size / FIRESTORE_DOC_LIMIT:.1f}% of 1 MiB)  "
            f"bands {dict(sorted(bands.items()))}  domains {dict(sorted(domains.items()))}  "
            f"θ {dict(template.theta)}"
        )
        if template.missing:
            print(f"  anchors not in this graph: {', '.join(template.missing)}")
        docs[template_path(key)] = doc
    if not args.write:
        print("dry run: pass --write to store the templates")
        return 0

    async def body(t: Txn) -> None:
        for path, doc in docs.items():
            t.set(path, doc)

    await get_doc_store().run(body)
    print(f"wrote {len(docs)} templates to persona_templates/")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--graph", help="local concepts.json instead of CONCEPTS_URI")
    parser.add_argument("--write", action="store_true", help="store the templates in Firestore")
    sys.exit(asyncio.run(main(parser.parse_args())))
