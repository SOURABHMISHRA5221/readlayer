"""Read-only demo persona templates, Firestore `persona_templates/{persona}` (DESIGN §4).

Written only by `scripts/seed_personas.py`; the API reads them, caches them per process and
never writes them. They are not user data, so they are outside export and delete. A demo
reader starts from their persona's template and gets a copy in
`users/{uid}/demo_graphs/{persona}` on their first event (app/store/reader_repo.py).
"""

import logging
import weakref
from datetime import UTC, datetime
from typing import Any

from app.graph.graph import ConceptGraph
from app.graph.loader import get_graph
from app.reader.personas import PERSONAS, PersonaTemplate, build_template
from app.reader.state import PersonaKey
from app.store.docstore import Doc, DocStore

log = logging.getLogger(__name__)

COLLECTION = "persona_templates"

# store → {(graph version, persona): template doc}
_cache: "weakref.WeakKeyDictionary[Any, dict[tuple[str, str], Doc]]" = weakref.WeakKeyDictionary()


def template_path(persona: PersonaKey) -> str:
    return f"{COLLECTION}/{persona}"


def template_to_doc(t: PersonaTemplate, graph: ConceptGraph, now: datetime) -> Doc:
    from app.store.reader_repo import edge_to_doc

    knows = {}
    for cid, edge in t.edges.items():
        concept = graph.get(cid)
        knows[cid] = edge_to_doc(edge, concept.domain if concept else "") | {"seeded": True}
    return {
        "persona": t.key,
        "version": t.version,
        "graph_version": t.graph_version,
        "theta": dict(t.theta),
        "threshold_offset": 0.0,
        "knows": knows,
        "created_at": now,
    }


async def get_template(store: DocStore, persona: PersonaKey) -> Doc:
    graph = get_graph()
    per_store = _cache.setdefault(store, {})
    key = (graph.version, persona)
    if key not in per_store:
        doc = await store.get(template_path(persona))
        if doc is None:
            # Not seeded yet (local dev, tests, a fresh project): build the same template in
            # memory from the spec. Production runs scripts/seed_personas.py after a deploy.
            log.warning("persona template missing, built in memory", extra={"persona": persona})
            now = datetime.now(UTC)
            doc = template_to_doc(
                build_template(persona, PERSONAS[persona], graph, now), graph, now
            )
        per_store[key] = doc
    return per_store[key]
