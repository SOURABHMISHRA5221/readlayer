"""Loads the concept graph at API startup and holds the process-wide instance."""

import logging

from app.graph.graph import ConceptGraph
from app.graph.models import ConceptGraphFile
from app.store.blob_repo import read_bytes

log = logging.getLogger("app.graph")

_graph = ConceptGraph.empty()


def get_graph() -> ConceptGraph:
    return _graph


def set_graph(graph: ConceptGraph) -> None:
    global _graph
    _graph = graph


async def load_graph(uri: str) -> ConceptGraph:
    """Empty graph when no URI is configured; any failure to load a configured one raises,
    so a deploy with a broken graph fails at startup instead of serving unlinked content.
    """
    if not uri:
        log.warning("CONCEPTS_URI not set; running without a concept graph")
        return ConceptGraph.empty()
    graph = ConceptGraph(ConceptGraphFile.model_validate_json(await read_bytes(uri)))
    if not graph.is_acyclic():
        raise ValueError(f"concept graph {uri} has prerequisite cycles")
    log.info("concept graph loaded", extra={"version": graph.version, "concepts": len(graph)})
    return graph


async def load_serving_graph(uri: str) -> int:
    """The graph as the API serves it: the file, then concepts grown online since it was
    written (M2.2). Sets the process-wide graph; returns the number of grown concepts. Used by
    API startup and by scripts that analyse content, which link nothing without it."""
    set_graph(await load_graph(uri))
    if not uri:
        return 0
    from app.graph.refresh import get_refresher

    try:
        return await get_refresher().load_startup()
    except Exception as exc:  # serve the file graph rather than fail to start
        log.warning("grown concepts not loaded", extra={"error_class": type(exc).__name__})
        return 0
