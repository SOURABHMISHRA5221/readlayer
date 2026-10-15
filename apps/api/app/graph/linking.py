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
from app.graph import jurisdiction
from app.graph.build import normalize_label
from app.graph.enrich import LinkQuestion, confirm_links
from app.graph.graph import ConceptGraph
from app.graph.growth_need import EMBED_TYPES
from app.graph.models import Concept
from app.ingest.models import Demand

log = logging.getLogger("app.graph.linking")

LinkMethod = Literal["alias", "confirmed", "unlinked"]
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


_TRAILING_PAREN = re.compile(r" \(([^()]*)\)$")
_SENSE_RUN = re.compile(r"[a-z]{3,}")


def sense_of(name: str) -> str | None:
    """The sense in a trailing " (x)" that names one: after a final "s" is dropped, x holds a run
    of 3+ lower-case letters ("Pip (finance)", "Duration (bond)"), unlike an acronym ("(OMO)",
    "(OEMs)", "(RoDTEP)", "(M1, M2, M3)") or no trailing parenthesis ("401(k)")."""
    m = _TRAILING_PAREN.search(name)
    if m is None:
        return None
    inner = m.group(1).strip()
    return inner if _SENSE_RUN.search(inner.removesuffix("s")) else None


def _sense_key(concept: Concept, key: str) -> str | None:
    """The sense a one-word key reaches this concept through, if any (decision 66): a
    sense-labelled concept's own sense whichever name matched ("exercised" → Exercise (options)),
    else an alias that normalises to the key and names a sense ("short" → "Short (finance)")."""
    if " " in key:
        return None
    if sense := sense_of(concept.label):
        return sense
    for name in concept.aliases:
        if normalize_label(name) == key and (sense := sense_of(name)):
            return sense
    return None


def _exact(graph: ConceptGraph, text: str, demand: Demand) -> Concept | None:
    concept = graph.lookup(text)
    if concept is None:
        return None
    sense = _sense_key(concept, normalize_label(text))
    if sense and f"({sense.casefold()})" not in f"{demand.label} {demand.anchor.exact}".casefold():
        return None  # "Pip" alone is not "Pip (finance)": the model decides (embedding + confirm)
    return concept


def exact_target(graph: ConceptGraph, demand: Demand) -> str | None:
    """Any exact label/alias match: the rule before decision 66 (`relink_senses` scopes with it)."""
    concept = graph.lookup(demand.label) or graph.lookup(demand.anchor.exact)
    return concept.id if concept else None


def alias_target(graph: ConceptGraph, demand: Demand) -> str | None:
    """An exact label/alias match, except a one-word key that reaches a sense-labelled name
    unless the demand itself names that sense (decision 66)."""
    concept = _exact(graph, demand.label, demand) or _exact(graph, demand.anchor.exact, demand)
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
    site: str = "",
    url: str = "",
) -> LinkPlan:
    """Candidates of a jurisdictional kind from a country the paragraph gives no sign of are
    dropped before the model sees them (app/graph/jurisdiction.py)."""
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
        para = paragraphs.get(d.paragraph_id, "")
        article = jurisdiction.cues(site, url, para)
        kept = [
            c
            for c, s in near
            if s >= threshold and jurisdiction.allowed(c.kind, c.jurisdiction, article)
        ]
        score = {c.id: s for c, s in near}
        if kept:
            sentence = sentence_around(para, d.anchor.exact, d.anchor.prefix)
            questions.append(
                LinkQuestion(
                    d.id,
                    phrase(d),
                    sentence,
                    tuple((c.id, c.label, c.definition, score[c.id]) for c in kept),
                    site=site,
                    kinds=tuple(c.kind or "" for c in kept),
                    jurisdictions=tuple(c.jurisdiction for c in kept),
                    article=tuple(sorted(article)),
                )
            )
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
    site: str = "",
    url: str = "",
) -> tuple[list[Demand], list[Link]]:
    """Link at ingest. If embeddings or the model are unavailable, alias links still apply."""
    if confirm is None:

        async def confirm(questions: Sequence[LinkQuestion]) -> dict[int, str | None]:
            return await confirm_links(questions, llm.run_with_meta, [])

    labels = pending_labels(graph, demands)
    vectors: dict[str, list[float]] = {}
    plan = plan_links(graph, demands, {}, paragraphs, threshold, site, url)
    answers: dict[int, str | None] = {}
    try:
        if labels:
            vectors = dict(zip(labels, await embed(labels), strict=True))
        plan = plan_links(graph, demands, vectors, paragraphs, threshold, site, url)
        if plan.questions:
            answers = await confirm(plan.questions)
    except llm.LLMError as exc:
        log.warning("entity linking by exact match only", extra={"error_class": type(exc).__name__})
    links = finish_links(demands, plan, answers)
    return apply_links(demands, links), links
