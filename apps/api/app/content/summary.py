"""Library facts derived from a stored doc and the concept graph. Pure: no I/O."""

from collections import Counter

from app.graph.graph import ConceptGraph
from app.ingest.models import ContentDoc


def article_domain(doc: ContentDoc, graph: ConceptGraph) -> str | None:
    """The article's topic: the graph domain carrying the most salience among its linked
    concepts (ties → alphabetical, so it is stable). None when nothing is linked."""
    weight: Counter[str] = Counter()
    for d in doc.demands:
        concept = graph.get(d.target_id) if d.target_id else None
        if concept is not None:
            weight[concept.domain] += d.salience
    if not weight:
        return None
    return min(weight, key=lambda domain: (-weight[domain], domain))
