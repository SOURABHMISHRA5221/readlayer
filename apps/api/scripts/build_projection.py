"""Cost projection for a concept build (`build_concepts --project`). Makes no LLM calls.

Embeds new candidate labels (cached for the real run, fractions of a cent) so the merge-pair
count is exact, and counts merge batches already in the build cache as free. Later passes depend
on model answers, so they use upper bounds: every merged candidate is defined, kept and gets a
prerequisite call; every concept/term mention not alias-matched by today's graph goes to
link_confirm. A margin covers re-asks for skipped items.
"""

import math
from dataclasses import dataclass

import numpy as np

from app import llm
from app.config import get_settings
from app.graph import build, enrich
from app.graph.graph import ConceptGraph
from app.graph.linking import EMBED_TYPES, alias_target
from app.ingest.models import ContentDoc
from scripts.build_cache import BuildCache

MARGIN = 1.25
WIKI_LOOKUPS = 600  # WIKI_BUDGET_S at one request per second
# M2 measured: of all pairs above DEDUPE_THRESHOLD, 5% were accepted merges.
M2_MERGE_ACCEPT_RATE = 0.05
BATCH = {
    "link_merge": 20,
    "concept_define": 25,
    "concept_prereqs": 15,
    "concept_wikidata": 20,
    "link_confirm": enrich.LINK_BATCH,
}


@dataclass
class Projection:
    rows: list[tuple[str, int, int, float]]  # task, items, uncached calls, cost
    embed_cost: float
    spent_today: float
    daily_budget: float

    @property
    def total(self) -> float:
        return round((sum(r[3] for r in self.rows) + self.embed_cost) * MARGIN, 3)

    @property
    def headroom(self) -> float:
        return round(self.daily_budget - self.spent_today, 3)

    def render(self) -> str:
        lines = ["| pass | items | uncached calls | cost |", "|---|---|---|---|"]
        lines += [f"| {t} | {n} | {c} | ${usd:.3f} |" for t, n, c, usd in self.rows]
        lines += [
            f"| embeddings (new labels) | | | ${self.embed_cost:.4f} |",
            "",
            f"Projected total with {MARGIN:.0%} margin: **${self.total:.2f}**",
            f"Spent today (UTC): ${self.spent_today:.3f} of ${self.daily_budget:.2f}; "
            f"headroom ${self.headroom:.2f}",
        ]
        return "\n".join(lines)


def _calls(n: int, task: str) -> int:
    return math.ceil(n / BATCH[task])


async def project(
    cands: list, docs: list[ContentDoc], graph: ConceptGraph, cache: BuildCache
) -> Projection:
    settings = get_settings()
    vectors = np.asarray(await cache.embed([c.display for c in cands], "SEMANTIC_SIMILARITY"))
    pairs = build.candidate_pairs(vectors, settings.dedupe_threshold, top_k=5)
    entries = [
        enrich.Entry(c.display, tuple(x for x in c.labels if x != c.display)[:4]) for c in cands
    ]
    merge_uncached = 0
    size = BATCH["link_merge"]
    for s in range(0, len(pairs), size):
        batch = [(entries[i], entries[j]) for i, j, _ in pairs[s : s + size]]
        prompt_vars = {"pair_count": len(batch), "pairs": enrich.render_pairs(batch)}
        merge_uncached += not cache.has("link_merge", prompt_vars)
    merge_uncached += _calls(40, "link_merge")  # band sample

    merged = max(len(cands) - round(M2_MERGE_ACCEPT_RATE * len(pairs)), 1)
    non_seed = sum(1 for c in cands if not c.seed_qid)
    wiki_items = min(non_seed, cache.wiki_cached() + WIKI_LOOKUPS)
    mentions = sum(
        1
        for doc in docs
        for d in doc.demands
        if d.type in EMBED_TYPES and alias_target(graph, d) is None
    )
    link_items = mentions + 150  # plus the evaluation sample

    rows = []
    for task, items, calls in (
        ("link_merge", len(pairs), merge_uncached),
        ("concept_define", merged, _calls(merged, "concept_define")),
        ("concept_wikidata", wiki_items, _calls(wiki_items, "concept_wikidata")),
        ("concept_prereqs", merged, _calls(merged, "concept_prereqs")),
        ("link_confirm", link_items, _calls(link_items, "link_confirm")),
    ):
        rows.append((task, items, calls, calls * cache.cost_per_call(task)))
    spent = await llm.get_spend_store().get_today()
    return Projection(rows, cache.embed_cost_new, spent, settings.llm_daily_budget_usd)
