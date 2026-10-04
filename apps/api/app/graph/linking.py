"""Entity linking of demands to concept ids (DESIGN §2).

1. Exact match of the demand's label or anchor text on a concept label/alias (any type: the
   extraction prompt tags institutions such as RBI or SEBI as `context`).
2. Concept and term demands only: embed the demand's label and take the concepts whose label
   embeddings are most similar (top 5, cosine ≥ LINK_THRESHOLD) as candidates; the model then
   picks the candidate whose glossary entry explains the mention in its sentence, or none.
   Embedding similarity alone can't separate a concept from its near neighbours (checked on the
   M2 corpus), so it only proposes candidates. Context demands never take this path, since
   events and people would land on whatever concept is semantically closest.
Anything else stays `target_id = None` (unlinked; still usable as a term demand).
"""

import logging
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from app import llm
from app.graph.enrich import LinkQuestion, confirm_links
from app.graph.graph import ConceptGraph
from app.ingest.models import Demand

log = logging.getLogger("app.graph.linking")

LinkMethod = Literal["alias", "confirmed", "unlinked"]
EMBED_TYPES = frozenset({"concept", "term"})
CANDIDATES = 5
SENTENCE_MAX_CHARS = 300
_SENTENCE_END = re.compile(r"[.!?][\"'”’)]?\s+")

EmbedTexts = Callable[[list[str]], Awaitable[list[list[float]]]]


@dataclass(frozen=True)
class Link:
    demand_id: str
    target_id: str | None
    method: LinkMethod
    score: float | None = None  # label cosine of the chosen (or best) candidate


Confirm = Callable[[Sequence[LinkQuestion]], Awaitable[dict[int, str | None]]]


def sentence_around(text: str, exact: str, prefix: str = "") -> str:
    """The sentence of `text` containing the anchor, capped around it."""
    hit = text.find(prefix + exact) if prefix else -1
    pos = hit + len(prefix) if hit >= 0 else text.find(exact)
    if pos < 0:
        return exact
    starts = [m.end() for m in _SENTENCE_END.finditer(text, 0, pos)]
    start = starts[-1] if starts else 0
    end_match = _SENTENCE_END.search(text, pos + len(exact))
    end = end_match.start() + 1 if end_match else len(text)
    if end - start > SENTENCE_MAX_CHARS:
        half = (SENTENCE_MAX_CHARS - len(exact)) // 2
        start, end = max(start, pos - half), min(end, pos + len(exact) + half)
    return text[start:end].strip()


def query_text(demand: Demand, paragraph_text: str) -> str:
    sentence = sentence_around(paragraph_text, demand.anchor.exact, demand.anchor.prefix)
    return f"{demand.label} — {sentence}"


def alias_target(graph: ConceptGraph, demand: Demand) -> str | None:
    concept = graph.lookup(demand.label) or graph.lookup(demand.anchor.exact)
    return concept.id if concept else None


def phrase(demand: Demand) -> str:
    if demand.anchor.exact.casefold() == demand.label.casefold():
        return demand.label
    return f"{demand.anchor.exact} ({demand.label})"


# ---------------------------------------------------------------- pure planning


@dataclass(frozen=True)
class LinkPlan:
    alias: dict[str, str]  # demand id -> concept id
    questions: list[LinkQuestion]
    best_score: dict[str, float]  # demand id -> best candidate cosine (embedded demands)


def pending_labels(graph: ConceptGraph, demands: Sequence[Demand]) -> list[str]:
    """Labels that need an embedding: concept/term demands without an exact match."""
    if not len(graph):
        return []
    return sorted(
        {d.label for d in demands if d.type in EMBED_TYPES and alias_target(graph, d) is None}
    )


def plan_links(
    graph: ConceptGraph,
    demands: Sequence[Demand],
    label_vectors: dict[str, list[float]],
    paragraphs: dict[str, str],
    threshold: float,
) -> LinkPlan:
    alias: dict[str, str] = {}
    questions: list[LinkQuestion] = []
    best: dict[str, float] = {}
    if not len(graph):
        return LinkPlan(alias, questions, best)
    for d in demands:
        if target := alias_target(graph, d):
            alias[d.id] = target
            continue
        if d.type not in EMBED_TYPES or d.label not in label_vectors:
            continue
        near = graph.nearest(label_vectors[d.label], CANDIDATES)
        best[d.id] = near[0][1]
        cands = tuple((c.id, c.label, c.definition, s) for c, s in near if s >= threshold)
        if cands:
            para = paragraphs.get(d.paragraph_id, "")
            sentence = sentence_around(para, d.anchor.exact, d.anchor.prefix)
            questions.append(LinkQuestion(d.id, phrase(d), sentence, cands))
    return LinkPlan(alias, questions, best)


def finish_links(
    demands: Sequence[Demand], plan: LinkPlan, answers: dict[int, str | None]
) -> list[Link]:
    """Combine alias links with the model's answers (ids outside the candidates are ignored)."""
    chosen: dict[str, tuple[str, float]] = {}
    for i, q in enumerate(plan.questions):
        pick = answers.get(i)
        score = next((s for cid, *_, s in q.candidates if cid == pick), None)
        if pick and score is not None:
            chosen[q.demand_id] = (pick, score)
    links = []
    for d in demands:
        if d.id in plan.alias:
            links.append(Link(d.id, plan.alias[d.id], "alias"))
        elif d.id in chosen:
            links.append(Link(d.id, chosen[d.id][0], "confirmed", chosen[d.id][1]))
        else:
            links.append(Link(d.id, None, "unlinked", plan.best_score.get(d.id)))
    return links


def apply_links(demands: Sequence[Demand], links: Sequence[Link]) -> list[Demand]:
    by_id = {link.demand_id: link.target_id for link in links}
    return [d.model_copy(update={"target_id": by_id.get(d.id)}) for d in demands]


# ---------------------------------------------------------------- ingest path


async def _embed_labels(texts: list[str]) -> list[list[float]]:
    return (await llm.embed(texts, task_type="SEMANTIC_SIMILARITY")).vectors


async def link_demands(
    graph: ConceptGraph,
    demands: Sequence[Demand],
    paragraphs: dict[str, str],
    threshold: float,
    embed: EmbedTexts = _embed_labels,
    confirm: Confirm | None = None,
) -> tuple[list[Demand], list[Link]]:
    """Link at ingest. If embeddings or the model are unavailable, alias links still apply."""
    if confirm is None:

        async def confirm(questions: Sequence[LinkQuestion]) -> dict[int, str | None]:
            return await confirm_links(questions, llm.run_with_meta, [])

    labels = pending_labels(graph, demands)
    vectors: dict[str, list[float]] = {}
    plan = plan_links(graph, demands, {}, paragraphs, threshold)
    answers: dict[int, str | None] = {}
    try:
        if labels:
            vectors = dict(zip(labels, await embed(labels), strict=True))
        plan = plan_links(graph, demands, vectors, paragraphs, threshold)
        if plan.questions:
            answers = await confirm(plan.questions)
    except llm.LLMError as exc:
        log.warning("entity linking by exact match only", extra={"error_class": type(exc).__name__})
    links = finish_links(demands, plan, answers)
    return apply_links(demands, links), links
