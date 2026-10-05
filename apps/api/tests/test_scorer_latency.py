"""BUILD_PLAN M4 acceptance: scoring p95 under 150 ms for a 1,200-word article (warm).

A synthetic graph the size of the real one (3,300 concepts, up to 3 prerequisites each), a
reader with 300 KNOWS edges and an article with 60 demands across 12 paragraphs.
"""

import random
import time
from datetime import UTC, datetime, timedelta

from app.content.router import p95
from app.graph.graph import ConceptGraph
from app.graph.models import ConceptGraphFile
from app.ingest.models import StoredParagraph
from app.reader.state import ReaderState
from app.scoring import scorer as sc
from app.scoring.scorer import ScoringInputs
from tests.test_scorer import concept, demand, doc, edge

N_CONCEPTS = 3300
DOMAINS = ("economics", "finance", "business", "policy")
RUNS = 200
P95_BUDGET_MS = 150


def build():
    rnd = random.Random(7)
    concepts = []
    for i in range(N_CONCEPTS):
        prereqs = (
            sorted({f"c_k{rnd.randrange(i):04d}" for _ in range(rnd.randint(0, 3))}) if i else []
        )
        concepts.append(concept(f"c_k{i:04d}", DOMAINS[i % 4], rnd.uniform(-2, 2), prereqs[:3]))
    graph = ConceptGraph(ConceptGraphFile(version="perf", concepts=concepts))
    now = datetime(2026, 10, 8, tzinfo=UTC)
    edges = {
        f"c_k{rnd.randrange(N_CONCEPTS):04d}": edge(
            rnd.random(), conf=rnd.uniform(1, 8), at=now - timedelta(days=rnd.randrange(120))
        )
        for _ in range(300)
    }
    state = ReaderState(theta={d: rnd.uniform(-1.5, 1.5) for d in DOMAINS}, edges=edges)
    paragraphs = [StoredParagraph(id=f"p{i}", text="word " * 100, structure=rnd.random())
                  for i in range(12)]  # fmt: skip
    kinds = ("concept", "concept", "concept", "term", "context")
    demands = [
        demand(
            f"d{i}",
            f"c_k{rnd.randrange(N_CONCEPTS):04d}" if i % 7 else None,
            pid=f"p{i % 12}",
            start=i * 90,
            type_=kinds[i % 5],
            salience=rnd.uniform(0.3, 1.0),
            explained=i % 6 == 0,
            zipf=rnd.uniform(2, 5),
        )
        for i in range(60)
    ]
    article = doc(demands, paragraphs)
    inputs = ScoringInputs(explainers={}, engaged_entities=frozenset({"c_k0001"}))
    return graph, state, article, inputs, now


def test_scoring_p95_under_150ms_for_a_1200_word_article():
    graph, state, article, inputs, now = build()
    assert sc.word_count(article) == 1200
    sc.annotate(article, graph, state, "balanced", now, inputs)  # warm
    times = []
    for _ in range(RUNS):
        started = time.perf_counter()
        result = sc.annotate(article, graph, state, "balanced", now, inputs)
        times.append((time.perf_counter() - started) * 1000)
    print(f"scoring p95 {p95(times):.2f} ms, median {sorted(times)[RUNS // 2]:.2f} ms")
    assert result.spans
    assert p95(times) < P95_BUDGET_MS
