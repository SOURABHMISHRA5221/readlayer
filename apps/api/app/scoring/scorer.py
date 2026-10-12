"""Gap scorer and annotation budget (DESIGN §5–6). Pure: no I/O, no SDK imports, no LLM.

`annotate` scores every demand in an article against one reader's state and returns the
budgeted spans, paragraph markers, the pre-read path and at most one uncertainty prompt.
Same inputs → same output: every ranking breaks ties on reading order, then ids.
"""

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from app.content.summary import article_domain
from app.graph.graph import ConceptGraph
from app.graph.models import Concept
from app.ingest.models import Anchor, ContentDoc, Demand, is_corpus
from app.reader import model
from app.reader.state import Density, ReaderState
from app.scoring import rules

WORDS_PER_SPAN = 80
MAX_SPANS_PER_PARAGRAPH = 2
PARAGRAPHS_PER_MARKER = 3
PREREAD_WEAK = 0.5  # an assumed concept below this starts the pre-read walk
PREREAD_KNOWN = 0.7  # the walk stops at a prerequisite known at least this well
PREREAD_MAX_STEPS = 3
REFRESHER_BANDS = frozenset({"understands", "can explain"})  # quieter highlight (Design pass A1)
PROMPT_MIN_SALIENCE = 0.7
PROMPT_P_RANGE = (0.35, 0.65)
PROMPT_MAX_CONFIDENCE = 4.0
PROMPTS_PER_DAY = 3


@dataclass(frozen=True)
class ExplainerRef:
    """A corpus article that explains a concept in its own text."""

    content_id: str
    title: str
    words: int


@dataclass(frozen=True)
class ScoringInputs:
    """Reader-specific facts the router derives from the catalog (kept out of the scorer so
    it stays pure)."""

    engaged_entities: frozenset[str] = frozenset()
    explainers: Mapping[str, ExplainerRef] = field(default_factory=dict)
    prompted_today: tuple[str, ...] = ()  # content ids that already got a prompt today
    prompts_allowed: bool = True  # no prompts while learning is paused: answers wouldn't count


@dataclass(frozen=True)
class Scored:
    demand: Demand
    concept: Concept | None
    p_know: float
    score: float
    order: int  # reading order in the article


@dataclass(frozen=True)
class SpanAnnotation:
    demand_id: str
    paragraph_id: str
    anchor: Anchor
    concept_id: str
    label: str
    definition: str
    domain: str
    base_difficulty: float
    prerequisites: tuple[str, ...]
    p_know: float
    salience: float
    score: float
    # The reader's band for the concept itself (edge or prior, no prerequisite cap): the band
    # the explanation is written for (explain.inputs.concept_band), so highlight, card and recap
    # agree. Design pass A1.
    band: model.Band = "unaware"

    @property
    def level(self) -> str:
        return "refresher" if self.band in REFRESHER_BANDS else "new"


@dataclass(frozen=True)
class ParagraphMarker:
    paragraph_id: str
    score: float
    domain: str | None


@dataclass(frozen=True)
class PrereadStep:
    concept_id: str
    label: str
    definition: str
    p_know: float
    article: ExplainerRef | None  # else the card shows the definition
    known: bool = False  # the prerequisite where the walk stopped, shown ticked (Design pass A2)


@dataclass(frozen=True)
class Preread:
    score: float  # mean span_score of the assumed concepts
    concept_id: str  # the article concept the path leads to
    steps: tuple[PrereadStep, ...]  # most basic first


@dataclass(frozen=True)
class UncertaintyPrompt:
    demand_id: str
    paragraph_id: str
    anchor: Anchor
    concept_id: str
    label: str
    p_know: float
    salience: float


@dataclass(frozen=True)
class Annotations:
    spans: tuple[SpanAnnotation, ...]
    paragraphs: tuple[ParagraphMarker, ...]
    preread: Preread | None
    prompt: UncertaintyPrompt | None


def word_count(doc: ContentDoc) -> int:
    return sum(len(p.text.split()) for p in doc.paragraphs)


# ---------------------------------------------------------------- scoring


def score_demands(
    doc: ContentDoc,
    graph: ConceptGraph,
    state: ReaderState,
    now: datetime,
    inputs: ScoringInputs,
) -> list[Scored]:
    """Every demand that can be scored, in reading order."""
    domain = article_domain(doc, graph)
    ordered = sorted(doc.demands, key=lambda d: (d.anchor.start, d.id))
    out = []
    for order, d in enumerate(ordered):
        concept = graph.get(d.target_id) if d.target_id else None
        p = rules.demand_p(d, concept, graph, state, now, domain, inputs.engaged_entities)
        if p is not None:
            out.append(Scored(d, concept, p, rules.span_score(p, d.salience, d.explained_in_text),
                              order))  # fmt: skip
    return out


def first_occurrences(scored: Iterable[Scored]) -> list[Scored]:
    """The first linked occurrence of each concept (DESIGN §6.2); spans need a concept."""
    seen: set[str] = set()
    out = []
    for s in scored:
        if s.concept is not None and s.concept.id not in seen:
            seen.add(s.concept.id)
            out.append(s)
    return out


# ---------------------------------------------------------------- selection


def select_spans(
    firsts: Sequence[Scored], state: ReaderState, words: int, cut: float
) -> list[Scored]:
    candidates = sorted(
        (
            s
            for s in firsts
            if s.score >= cut and not rules.explicitly_known(state, s.concept.id)  # type: ignore[union-attr]
        ),
        key=lambda s: (-s.score, s.order),
    )
    budget = max(1, words // WORDS_PER_SPAN)
    per_paragraph: Counter[str] = Counter()
    chosen: list[Scored] = []
    for s in candidates:
        if len(chosen) >= budget:
            break
        if per_paragraph[s.demand.paragraph_id] >= MAX_SPANS_PER_PARAGRAPH:
            continue
        per_paragraph[s.demand.paragraph_id] += 1
        chosen.append(s)
    return chosen


def paragraph_domain(items: Sequence[Scored], fallback: str | None) -> str | None:
    weight: Counter[str] = Counter()
    for s in items:
        if s.concept is not None:
            weight[s.concept.domain] += s.demand.salience
    if not weight:
        return fallback
    return min(weight, key=lambda d: (-weight[d], d))


def select_paragraphs(
    doc: ContentDoc,
    scored: Sequence[Scored],
    state: ReaderState,
    fallback_domain: str | None,
    cut: float,
) -> list[ParagraphMarker]:
    by_para: dict[str, list[Scored]] = {}
    for s in scored:
        by_para.setdefault(s.demand.paragraph_id, []).append(s)
    markers = []
    for index, para in enumerate(doc.paragraphs):
        items = by_para.get(para.id, [])
        # One concept or entity counts once per paragraph, at its highest score.
        best: dict[str, float] = {}
        for s in items:
            key = rules.entity_key(s.demand)
            best[key] = max(best.get(key, 0.0), s.score)
        domain = paragraph_domain(items, fallback_domain)
        score = rules.paragraph_score(
            list(best.values()), para.structure, rules.theta_of(state, domain)
        )
        if score >= cut:
            markers.append((score, index, ParagraphMarker(para.id, score, domain)))
    markers.sort(key=lambda m: (-m[0], m[1]))
    budget = max(1, len(doc.paragraphs) // PARAGRAPHS_PER_MARKER)
    return [m for _, _, m in markers[:budget]]


def preread_path(
    firsts: Sequence[Scored],
    graph: ConceptGraph,
    state: ReaderState,
    now: datetime,
    inputs: ScoringInputs,
    doc_id: str,
    cut: float,
) -> Preread | None:
    """DESIGN §6.4: triggered when the assumed concepts' mean span_score passes the pre-read
    threshold. From the weakest-known high-scoring assumed concept, walk to its weakest
    prerequisite until one is known at ≥ 0.7; ≤ 3 steps, returned most basic first. When the
    walk stops at a known prerequisite, that one leads the path as a ticked step (ties: highest
    p, then id), so the reader sees where the path starts from."""
    assumed = [s for s in firsts if not s.demand.explained_in_text and s.demand.type == "concept"]
    if not assumed:
        return None
    mean = sum(s.score for s in assumed) / len(assumed)
    if mean < cut:
        return None
    weak = [s for s in assumed if s.p_know < PREREAD_WEAK]
    if not weak:
        return None
    start = min(weak, key=lambda s: (-s.score, s.order)).concept
    assert start is not None
    path = [start]
    while len(path) < PREREAD_MAX_STEPS:
        on_path = {c.id for c in path}
        options = [
            (rules.concept_p(q, state, now), q.id, q)
            for q in graph.prerequisites(path[-1].id)
            if q.id not in on_path
        ]
        unknown = [o for o in options if o[0] < PREREAD_KNOWN]
        if not unknown:
            known = [o for o in options if o[0] >= PREREAD_KNOWN]
            reached = min(known, key=lambda o: (-o[0], o[1]))[2] if known else None
            break
        path.append(min(unknown, key=lambda o: (o[0], o[1]))[2])
    else:
        reached = None  # stopped at the step limit: no known prerequisite reached

    def step(c: Concept, known: bool) -> PrereadStep:
        ref = inputs.explainers.get(c.id)
        return PrereadStep(
            concept_id=c.id,
            label=c.label,
            definition=c.definition,
            p_know=rules.concept_p(c, state, now),
            article=ref if ref and ref.content_id != doc_id else None,
            known=known,
        )

    steps = ((step(reached, True),) if reached is not None else ()) + tuple(
        step(c, False) for c in reversed(path)
    )
    return Preread(score=mean, concept_id=start.id, steps=steps)


def _confidence(state: ReaderState, concept: Concept, now: datetime) -> float:
    edge = state.edges.get(concept.id)
    if edge is None:
        return model.K_PRIOR
    p0 = model.prior(rules.theta_of(state, concept.domain), concept.base_difficulty)
    return model.confidence(model.forget(edge, p0, now))


def uncertainty_prompt(
    firsts: Sequence[Scored],
    shown: set[str],
    state: ReaderState,
    now: datetime,
    inputs: ScoringInputs,
    doc_id: str,
) -> UncertaintyPrompt | None:
    """DESIGN §6.5: "Know this?" on a salient concept we're unsure about and didn't annotate.
    At most one per article and three per day (a reload of a prompted article keeps it)."""
    if not inputs.prompts_allowed:
        return None
    if doc_id not in inputs.prompted_today and len(inputs.prompted_today) >= PROMPTS_PER_DAY:
        return None
    lo, hi = PROMPT_P_RANGE
    candidates = []
    for s in firsts:
        c = s.concept
        if c is None or c.id in shown or rules.explicitly_known(state, c.id):
            continue
        p = rules.concept_p(c, state, now)
        if (
            s.demand.salience >= PROMPT_MIN_SALIENCE
            and lo <= p <= hi
            and _confidence(state, c, now) < PROMPT_MAX_CONFIDENCE
        ):
            candidates.append((-s.demand.salience, abs(p - 0.5), s.order, s, p))
    if not candidates:
        return None
    _, _, _, s, p = min(candidates, key=lambda row: row[:3])
    c = s.concept
    assert c is not None
    return UncertaintyPrompt(
        s.demand.id, s.demand.paragraph_id, s.demand.anchor, c.id, c.label, p, s.demand.salience
    )


# ---------------------------------------------------------------- entry point


def annotate(
    doc: ContentDoc,
    graph: ConceptGraph,
    state: ReaderState,
    density: Density,
    now: datetime,
    inputs: ScoringInputs | None = None,
) -> Annotations:
    inputs = inputs or ScoringInputs()
    offset = state.threshold_offset
    scored = score_demands(doc, graph, state, now, inputs)
    firsts = first_occurrences(scored)
    spans = select_spans(firsts, state, word_count(doc), rules.threshold(density, "span", offset))
    paragraphs = select_paragraphs(
        doc,
        scored,
        state,
        article_domain(doc, graph),
        rules.threshold(density, "paragraph", offset),
    )
    preread = preread_path(
        firsts,
        graph,
        state,
        now,
        inputs,
        doc.content_id,
        rules.threshold(density, "preread", offset),
    )
    shown = {s.concept.id for s in spans if s.concept is not None}
    prompt = uncertainty_prompt(firsts, shown, state, now, inputs, doc.content_id)
    return Annotations(
        spans=tuple(_span(s, graph, state, now) for s in spans),
        paragraphs=tuple(paragraphs),
        preread=preread,
        prompt=prompt,
    )


def _span(s: Scored, graph: ConceptGraph, state: ReaderState, now: datetime) -> SpanAnnotation:
    c = s.concept
    assert c is not None
    return SpanAnnotation(
        demand_id=s.demand.id,
        paragraph_id=s.demand.paragraph_id,
        anchor=s.demand.anchor,
        concept_id=c.id,
        label=c.label,
        definition=c.definition,
        domain=c.domain,
        base_difficulty=c.base_difficulty,
        prerequisites=tuple(q.label for q in graph.prerequisites(c.id))[:3],
        p_know=s.p_know,
        salience=s.demand.salience,
        score=s.score,
        band=model.band_of(rules.concept_p(c, state, now)),
    )


# ---------------------------------------------------------------- catalog-derived inputs


def explainer_index(docs: Iterable[ContentDoc]) -> dict[str, ExplainerRef]:
    """Concept → the shortest corpus article explaining it in its own text (pre-read links).
    Reader-brought pages (NOT_CORPUS) are never linked."""
    best: dict[str, ExplainerRef] = {}
    for doc in docs:
        if not is_corpus(doc):
            continue
        words = word_count(doc)
        for d in doc.demands:
            if not (d.explained_in_text and d.target_id):
                continue
            ref = ExplainerRef(doc.content_id, doc.title, words)
            cur = best.get(d.target_id)
            if cur is None or (ref.words, ref.content_id) < (cur.words, cur.content_id):
                best[d.target_id] = ref
    return best


def engaged_entities(
    docs_by_id: Mapping[str, ContentDoc], content_ids: Iterable[str], exclude: str
) -> frozenset[str]:
    """Entities mentioned in contents the reader engaged with recently (context rule)."""
    out: set[str] = set()
    for cid in content_ids:
        doc = docs_by_id.get(cid)
        if doc is None or cid == exclude:
            continue
        out.update(rules.entity_key(d) for d in doc.demands)
    return frozenset(out)
