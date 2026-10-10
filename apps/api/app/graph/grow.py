"""Online concept growth at ingest (M2.2 plan §C.2): the calls and the store.

Given an analysed article's demands and a number of growth slots (reserved in phase 1 within the
caps), it grows at most that many verified concepts for still-unlinked concept/term demands:
1. pick the unlinked demands (one per label, most salient first);
2. embed their labels; a near graph concept (≥ DEDUPE_THRESHOLD) goes to one batched link_merge,
   and a "same" answer links the demand to it (named organisations never absorb another label);
3. the rest go to one batched concept_define (v3) with their sentence; only verified concepts
   are kept (taxonomy domain, kept kind, specialization ≥ 2);
4. one batched concept_prereqs over the 20 nearest and 20 most basic same-domain concepts,
   existing ids only, acyclic;
5. each concept is stored create-if-absent in `graph_growth/`; a concept another instance stored
   first under the same id is reused when it has the same label, skipped otherwise.
Every call goes through app/llm.py (budget, retries, fallback). Article text is untrusted: it
reaches the model only inside the prompts' content delimiters and every answer is
schema-validated, so injected instructions can't produce anything outside the schema.
"""

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field

from wordfreq import zipf_frequency

from app import llm
from app.config import get_settings
from app.graph import enrich
from app.graph.build import normalize_label, slug_ids
from app.graph.graph import ConceptGraph
from app.graph.growth import (
    GrowthPick,
    keep_prereqs,
    make_concept,
    merge_refused,
    pick,
    prereq_pool,
    unique_id,
    verified,
)
from app.graph.models import Concept
from app.ingest.models import Demand
from app.store.growth_repo import GrowthRepo

Embed = Callable[[list[str]], Awaitable[list[list[float]]]]


@dataclass
class GrowthOutcome:
    links: dict[str, str] = field(default_factory=dict)  # demand id -> concept id
    grown: set[str] = field(default_factory=set)  # demand ids linked to a concept grown here
    added: list[Concept] = field(default_factory=list)
    merged: int = 0
    rejected: int = 0
    calls: list[llm.CallMeta] = field(default_factory=list)

    @property
    def cost_usd(self) -> float:
        return sum(m.cost_usd for m in self.calls)


async def _embed(texts: list[str]) -> list[list[float]]:
    return (await llm.embed(texts, task_type="SEMANTIC_SIMILARITY")).vectors


async def grow(
    graph: ConceptGraph,
    demands: Sequence[Demand],
    paragraphs: dict[str, str],
    slots: int,
    source_cid: str,
    repo: GrowthRepo,
    runner: enrich.Runner = llm.run_with_meta,
    embed: Embed = _embed,
) -> GrowthOutcome:
    out = GrowthOutcome()
    picks = pick(demands, paragraphs, slots)
    if not picks or not len(graph):
        return out
    vectors = dict(
        zip([p.label for p in picks], await embed([p.label for p in picks]), strict=True)
    )
    rest = await _merge_known(graph, picks, vectors, runner, out)
    if not rest:
        return out
    entries = [enrich.Entry(p.label, snippets=(p.sentence,)) for p in rest]
    infos = await enrich.define_concepts(entries, runner, out.calls)
    candidates: list[tuple[GrowthPick, Concept]] = []
    taken = {c.id for c in graph.concepts}
    for i, p in enumerate(rest):
        info = infos.get(i)
        zipf = zipf_frequency(p.label, "en")
        if info is None or not verified(info, p.label, zipf):
            out.rejected += 1
            continue
        cid = unique_id(slug_ids([p.label])[0], taken)
        taken.add(cid)
        candidates.append((p, make_concept(cid, p.label, info, zipf, vectors[p.label])))
    candidates = await _confirm(candidates, runner, out)
    if not candidates:
        return out
    requests = [
        enrich.PrereqRequest(
            enrich.Entry(c.label, definition=c.definition),
            tuple((x.id, x.label) for x in prereq_pool(graph, vectors[p.label], c.domain)),
        )
        for p, c in candidates
    ]
    picks_by = await enrich.propose_prereqs(requests, runner, out.calls)
    versions = {t: llm.load_prompt(t).version for t in ("concept_define", "concept_prereqs")}
    for k, (p, concept) in enumerate(candidates):
        concept = concept.model_copy(
            update={"prerequisites": keep_prereqs(graph, concept, picks_by.get(k, []))}
        )
        if await repo.create_if_absent(concept, source_cid, versions):
            out.added.append(concept)
            target = concept.id
        else:  # another instance stored this id first
            existing = await repo.get(concept.id)
            if existing is None or normalize_label(existing.concept.label) != normalize_label(
                concept.label
            ):
                out.rejected += 1
                continue
            out.added.append(existing.concept)
            target = existing.concept.id
        for did in p.demand_ids:
            out.links[did] = target
            out.grown.add(did)
    return out


async def _confirm(
    candidates: list[tuple[GrowthPick, Concept]], runner: enrich.Runner, out: GrowthOutcome
) -> list[tuple[GrowthPick, Concept]]:
    """The linker's own check on each new concept: would its definition explain the mention in
    its sentence (link_confirm, the same strictness as linking)? Drops definitions that miss the
    sense used ("18-month fuel cycle" ≠ the nuclear fuel cycle) and concepts made from a generic
    word. One batched call."""
    questions = [
        enrich.LinkQuestion(
            c.id, p.phrase or p.label, p.sentence, ((c.id, c.label, c.definition, 1.0),),
            kinds=(c.kind or "",), jurisdictions=(c.jurisdiction,),
        )
        for p, c in candidates
    ]  # fmt: skip
    answers = await enrich.confirm_links(questions, runner, out.calls)
    kept = [(p, c) for k, (p, c) in enumerate(candidates) if answers.get(k) == c.id]
    out.rejected += len(candidates) - len(kept)
    return kept


async def _merge_known(
    graph: ConceptGraph,
    picks: list[GrowthPick],
    vectors: dict[str, list[float]],
    runner: enrich.Runner,
    out: GrowthOutcome,
) -> list[GrowthPick]:
    """Link picks that turn out to be an existing concept; return the rest."""
    threshold = get_settings().dedupe_threshold
    asked: list[tuple[GrowthPick, Concept]] = []
    for p in picks:
        concept, score = graph.nearest(vectors[p.label], 1)[0]
        if score >= threshold and not merge_refused(concept, p.label):
            asked.append((p, concept))
    if not asked:
        return picks
    pairs = [(enrich.Entry(p.label), enrich.Entry(c.label, tuple(c.aliases[:5]))) for p, c in asked]
    answers = await enrich.check_merges(pairs, runner, out.calls)
    merged = set()
    for k, (p, concept) in enumerate(asked):
        if answers.get(k):
            merged.add(p.label)
            out.merged += 1
            for did in p.demand_ids:
                out.links[did] = concept.id
    return [p for p in picks if p.label not in merged]
