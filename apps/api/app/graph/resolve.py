"""Resolve bare concept names (from a profile edit) to graph concepts, through the same steps as
entity linking at ingest (DESIGN §2): exact label/alias first (free), then embedding candidates
and `link_confirm`. The model never supplies ids; at most MAX_BATCHES confirm calls per call."""

from collections.abc import Awaitable, Callable, Sequence

from app import llm
from app.graph.enrich import LINK_BATCH, LinkQuestion, confirm_links
from app.graph.graph import ConceptGraph

CANDIDATES = 5
MAX_BATCHES = 3  # ≤ 30 names reach the model, in batches of LINK_BATCH (10)

EmbedTexts = Callable[[list[str]], Awaitable[list[list[float]]]]
Confirm = Callable[[Sequence[LinkQuestion]], Awaitable[dict[int, str | None]]]


async def _embed(texts: list[str]) -> list[list[float]]:
    return (await llm.embed(texts, task_type="SEMANTIC_SIMILARITY")).vectors


async def resolve_names(
    graph: ConceptGraph,
    names: Sequence[str],
    threshold: float,
    *,
    embed: EmbedTexts = _embed,
    confirm: Confirm | None = None,
    ledger: list[llm.CallMeta] | None = None,
) -> tuple[dict[str, str], list[str]]:
    """(casefolded name → concept id, unresolved names). Embedding or model outages leave the
    exact matches only; the rest come back unresolved."""
    ledger = ledger if ledger is not None else []
    if confirm is None:

        async def confirm(qs: Sequence[LinkQuestion]) -> dict[int, str | None]:
            return await confirm_links(qs, llm.run_with_meta, ledger)

    ids: dict[str, str] = {}
    pending: list[str] = []
    for name in names:
        hit = graph.lookup(name)
        if hit is not None:
            ids[name.casefold()] = hit.id
        else:
            pending.append(name)
    pending = pending[: MAX_BATCHES * LINK_BATCH]
    if pending and len(graph):
        try:
            vectors = await embed(pending)
            questions: list[LinkQuestion] = []
            for name, vec in zip(pending, vectors, strict=True):
                near = graph.nearest(vec, CANDIDATES)
                cands = tuple((c.id, c.label, c.definition, s) for c, s in near if s >= threshold)
                if cands:
                    sentence = f"A reader describing what they know mentions: {name}"
                    questions.append(LinkQuestion(name, name, sentence, cands))
            answers = await confirm(questions) if questions else {}
            for i, q in enumerate(questions):
                if (pick := answers.get(i)) is not None:
                    ids[q.demand_id.casefold()] = pick
        except llm.LLMError:
            pass  # exact matches still apply; the rest are reported as unresolved
    unresolved = [n for n in names if n.casefold() not in ids]
    return ids, unresolved
