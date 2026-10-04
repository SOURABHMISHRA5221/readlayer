"""In-memory concept graph: lookup, prerequisites and nearest-concept search (DESIGN §2).

Pure: built from a parsed ConceptGraphFile; loading from GCS lives in app/graph/loader.py.
"""

import networkx as nx
import numpy as np

from app.graph.build import normalize_label
from app.graph.models import Concept, ConceptGraphFile


def alias_index(concepts: list[Concept]) -> dict[str, str]:
    """Normalised label/alias → concept id. Labels beat aliases; an alias shared by two
    concepts is ambiguous and left out, so it can only link via embeddings.
    """
    index: dict[str, str] = {}
    for c in concepts:
        index.setdefault(normalize_label(c.label), c.id)
    labels = set(index)
    owners: dict[str, set[str]] = {}
    for c in concepts:
        for alias in c.aliases:
            key = normalize_label(alias)
            if key and key not in labels:
                owners.setdefault(key, set()).add(c.id)
    index.update({k: next(iter(ids)) for k, ids in owners.items() if len(ids) == 1})
    index.pop("", None)
    return index


class ConceptGraph:
    def __init__(self, file: ConceptGraphFile) -> None:
        self.version = file.version
        self._concepts = list(file.concepts)
        self._by_id = {c.id: c for c in self._concepts}
        self._row = {c.id: i for i, c in enumerate(self._concepts)}
        self._alias = alias_index(self._concepts)
        self._dag = nx.DiGraph()
        self._dag.add_nodes_from(self._by_id)
        for c in self._concepts:
            self._dag.add_edges_from((p, c.id) for p in c.prerequisites if p in self._by_id)
        self._matrix = _normalised(
            np.asarray([c.embedding for c in self._concepts], dtype=np.float32)
        )

    @classmethod
    def empty(cls) -> "ConceptGraph":
        return cls(ConceptGraphFile(version="empty", concepts=[]))

    def __len__(self) -> int:
        return len(self._concepts)

    @property
    def concepts(self) -> list[Concept]:
        return list(self._concepts)

    def get(self, concept_id: str) -> Concept | None:
        return self._by_id.get(concept_id)

    def lookup(self, text: str) -> Concept | None:
        """Exact match on a normalised label or unambiguous alias."""
        cid = self._alias.get(normalize_label(text))
        return self._by_id[cid] if cid else None

    def prerequisites(self, concept_id: str) -> list[Concept]:
        if concept_id not in self._dag:
            return []
        return [self._by_id[p] for p in self._dag.predecessors(concept_id)]

    def dependents(self, concept_id: str) -> list[Concept]:
        """Concepts that list this one as a prerequisite (they build on it)."""
        if concept_id not in self._dag:
            return []
        return [self._by_id[s] for s in self._dag.successors(concept_id)]

    def prerequisite_chain(self, concept_id: str) -> list[Concept]:
        """Longest prerequisite path ending at the concept, most basic first."""
        if concept_id not in self._dag:
            return []
        nodes = nx.ancestors(self._dag, concept_id) | {concept_id}
        path = nx.dag_longest_path(self._dag.subgraph(nodes))
        return [self._by_id[n] for n in path] or [self._by_id[concept_id]]

    def is_acyclic(self) -> bool:
        return nx.is_directed_acyclic_graph(self._dag)

    def vector(self, concept_id: str) -> np.ndarray | None:
        row = self._row.get(concept_id)
        return None if row is None else self._matrix[row]

    def nearest(self, vector: list[float] | np.ndarray, k: int = 1) -> list[tuple[Concept, float]]:
        if not self._concepts:
            return []
        query = _normalised(np.asarray(vector, dtype=np.float32)[None, :])[0]
        if query.shape[0] != self._matrix.shape[1]:
            raise ValueError("query embedding dimension does not match the graph")
        scores = self._matrix @ query
        top = np.argsort(-scores)[:k]
        return [(self._concepts[i], float(scores[i])) for i in top]


def _normalised(matrix: np.ndarray) -> np.ndarray:
    if matrix.size == 0:
        return matrix.reshape(0, 0)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.where(norms == 0, 1, norms)
