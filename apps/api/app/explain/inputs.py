"""What an explanation may be built from (DESIGN §7). Pure: no I/O, no SDK imports.

Inputs are ONLY the span, its sentence and paragraph, the concept's definition and
prerequisites, the reader's band, one THINKS_IN frame and the explanation style. Never a uid,
uid_hash, email or reading history: the prompt variable sets are fixed (tested).

A card has two parts with their own prompts and cache entries: the restatement of the author
(`restate_vars`, no band or frame: shared by every reader) and the reader's Background
(`prompt_vars`, per band, frame and style).
"""

import hashlib
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from app.explain.models import Mode
from app.graph.graph import ConceptGraph
from app.graph.models import Concept
from app.ingest.models import ContentDoc, Demand, StoredParagraph
from app.reader import model
from app.reader.frames import Frame
from app.reader.model import Band
from app.reader.state import ExplanationStyle, ReaderState

PARAGRAPH_LABEL = "What this paragraph is saying"
MAX_PARAGRAPH_CONCEPTS = 3
MAX_PREREQUISITES = 3

STYLE_RULES: Mapping[ExplanationStyle, str] = {
    "short": "Background: one sentence, at most 25 words.",
    "normal": "Background: at most 3 short sentences, about 60 words in all.",
    "detailed": "Background: at most 5 sentences, about 110 words in all.",
}
# The restatement's length per style: faithfulness first, so these only trim.
RESTATE_STYLE_RULES: Mapping[ExplanationStyle, str] = {
    "short": "As few words as a faithful restatement allows.",
    "normal": "Plain sentences, about as long as the passage needs.",
    "detailed": "Plain sentences; you may unpack each clause of the passage in turn.",
}
BAND_RULES: Mapping[Band, str] = {
    "unaware": "The reader has probably never met this idea. Assume no prior knowledge, define "
    "the term plainly and explain any jargon you use.",
    "heard of": "The reader knows the word but not what it means. Give the core idea plainly.",
    "understands": "The reader knows the basics. Do not define the term; give only the nuance "
    "this passage needs, in at most 2 sentences.",
    "can explain": "The reader knows this well. Do not define the term; one sentence on what "
    "matters about it here, nothing more.",
}
# Sentence boundary: end punctuation, space, then something that can start a sentence.
_SENTENCE_END = re.compile(r"(?<=[.!?])[\"'”’)]*\s+(?=[\"'“‘(]?[A-Z0-9])")


@dataclass(frozen=True)
class ConceptBrief:
    concept_id: str
    label: str
    definition: str
    prerequisites: tuple[tuple[str, str], ...]  # (label, definition)


@dataclass(frozen=True)
class ExplainInputs:
    mode: Mode
    content_id: str
    paragraph_id: str
    span: str  # anchor.exact; the paragraph text in paragraph mode
    sentence: str  # the span's sentence; the paragraph in paragraph mode
    paragraph: str
    concepts: tuple[ConceptBrief, ...]  # the span's concept, or the paragraph's top concepts
    band: Band
    thinks_in: Frame | None  # the pick (THINKS_IN) or a map frame (decision 67)
    style: ExplanationStyle

    @property
    def label(self) -> str:
        if self.mode == "paragraph":
            return PARAGRAPH_LABEL
        return self.concepts[0].label if self.concepts else self.span

    @property
    def definition(self) -> str:
        """The definition-only card (fallback)."""
        if self.mode == "span":
            return self.concepts[0].definition if self.concepts else ""
        return " ".join(f"{c.label}: {c.definition}" for c in self.concepts)

    @property
    def concept_id(self) -> str | None:
        return self.concepts[0].concept_id if self.mode == "span" and self.concepts else None

    @property
    def span_hash(self) -> str:
        source = self.span if self.mode == "span" else f"para|{self.paragraph}"
        return sha1(f"{self.content_id}|{self.paragraph_id}|{source}")

    def restate_key(self, prompt_version: str) -> str:
        """The restatement: the same for every reader of this span at this style."""
        return sha1(f"restate|{self.span_hash}|{self.style}|{prompt_version}")

    def background_key(self, prompt_version: str) -> str:
        """The Background: per reader level, frame and style."""
        frame = self.thinks_in or "none"
        return sha1(f"{self.span_hash}|{self.band}|{frame}|{self.style}|{prompt_version}")

    def restate_vars(self, feedback: str = "none") -> dict[str, str]:
        """No band and no frame: the restatement must not depend on who reads it."""
        return {
            "mode": self.mode,
            "span": self.span,
            "sentence": self.sentence,
            "paragraph": self.paragraph,
            "concepts": _concepts_text(self.concepts),
            "style": self.style,
            "style_rule": RESTATE_STYLE_RULES[self.style],
            "feedback": feedback,
        }

    def prompt_vars(self, feedback: str = "none") -> dict[str, str]:
        """The Background prompt."""
        return {
            "mode": self.mode,
            "span": self.span,
            "sentence": self.sentence,
            "paragraph": self.paragraph,
            "concepts": _concepts_text(self.concepts),
            "band": self.band,
            "band_rule": BAND_RULES[self.band],
            "thinks_in": self.thinks_in or "none",
            "style": self.style,
            "style_rule": STYLE_RULES[self.style],
            "feedback": feedback,
        }

    def verify_vars(self, author_says: str) -> dict[str, str]:
        return {
            "mode": self.mode,
            "span": self.span,
            "paragraph": self.paragraph,
            "author_says": author_says,
        }

    def verify_background_vars(self, background: str) -> dict[str, str]:
        return {
            "mode": self.mode,
            "span": self.span,
            "paragraph": self.paragraph,
            "background": background,
        }


PROMPT_VAR_KEYS = frozenset(
    {
        "mode", "span", "sentence", "paragraph", "concepts", "band", "band_rule", "thinks_in",
        "style", "style_rule", "feedback",
    }
)  # fmt: skip
RESTATE_VAR_KEYS = frozenset(
    {"mode", "span", "sentence", "paragraph", "concepts", "style", "style_rule", "feedback"}
)


def sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _concepts_text(concepts: tuple[ConceptBrief, ...]) -> str:
    lines: list[str] = []
    for c in concepts:
        lines.append(f"- {c.label}: {c.definition}")
        lines += [f"  - prerequisite {label}: {d}" for label, d in c.prerequisites]
    return "\n".join(lines) or "none"


def split_sentences(text: str) -> list[tuple[int, str]]:
    """(start offset, sentence) pairs."""
    out: list[tuple[int, str]] = []
    start = 0
    for m in _SENTENCE_END.finditer(text):
        out.append((start, text[start : m.start()].strip()))
        start = m.end()
    out.append((start, text[start:].strip()))
    return [(s, t) for s, t in out if t]


def locate(paragraph: str, exact: str, prefix: str) -> int:
    """Offset of the anchor inside its paragraph: the occurrence whose preceding text matches
    the prefix best, else the first. -1 if absent."""
    hits = [m.start() for m in re.finditer(re.escape(exact), paragraph)]
    if not hits:
        return -1
    tail = prefix.strip()[-20:]
    for h in hits:
        if tail and paragraph[:h].rstrip().endswith(tail):
            return h
    return hits[0]


def sentence_at(paragraph: str, offset: int) -> str:
    sentences = split_sentences(paragraph)
    chosen = sentences[0][1] if sentences else paragraph
    for start, text in sentences:
        if start <= offset:
            chosen = text
    return chosen


def brief(concept: Concept, graph: ConceptGraph) -> ConceptBrief:
    prereqs = tuple((q.label, q.definition) for q in graph.prerequisites(concept.id))
    return ConceptBrief(concept.id, concept.label, concept.definition, prereqs[:MAX_PREREQUISITES])


def concept_band(concept: Concept, state: ReaderState, now: datetime) -> Band:
    """The reader's band for a concept: current p_know (forgetting applied) or the prior."""
    p0 = model.prior(state.theta.get(concept.domain, 0.0), concept.base_difficulty)
    edge = state.edges.get(concept.id)
    return model.band_of(model.current_p_know(edge, p0, now) if edge else p0)


def _paragraph(doc: ContentDoc, paragraph_id: str) -> StoredParagraph | None:
    return next((p for p in doc.paragraphs if p.id == paragraph_id), None)


def span_inputs(
    doc: ContentDoc,
    demand: Demand,
    graph: ConceptGraph,
    state: ReaderState,
    now: datetime,
    thinks_in: Frame | None,
    style: ExplanationStyle,
) -> ExplainInputs | None:
    """None when the demand isn't linked to a graph concept or its paragraph is missing."""
    concept = graph.get(demand.target_id) if demand.target_id else None
    para = _paragraph(doc, demand.paragraph_id)
    if concept is None or para is None:
        return None
    offset = locate(para.text, demand.anchor.exact, demand.anchor.prefix)
    return ExplainInputs(
        mode="span",
        content_id=doc.content_id,
        paragraph_id=para.id,
        span=demand.anchor.exact,
        sentence=sentence_at(para.text, max(offset, 0)),
        paragraph=para.text,
        concepts=(brief(concept, graph),),
        band=concept_band(concept, state, now),
        thinks_in=thinks_in,
        style=style,
    )


def paragraph_inputs(
    doc: ContentDoc,
    paragraph_id: str,
    graph: ConceptGraph,
    state: ReaderState,
    thinks_in: Frame | None,
    style: ExplanationStyle,
) -> ExplainInputs | None:
    """A paragraph explainer: its most salient linked concepts give the definitions, and the
    band is the reader's domain ability prior (b = 0) in the most salient domain."""
    para = _paragraph(doc, paragraph_id)
    if para is None:
        return None
    linked: dict[str, tuple[float, Concept]] = {}
    for d in doc.demands:
        c = graph.get(d.target_id) if d.paragraph_id == paragraph_id and d.target_id else None
        if c is not None and d.salience > linked.get(c.id, (-1.0, c))[0]:
            linked[c.id] = (d.salience, c)
    top = sorted(linked.values(), key=lambda sc: (-sc[0], sc[1].id))[:MAX_PARAGRAPH_CONCEPTS]
    concepts = tuple(brief(c, graph) for _, c in top)
    weight: Counter[str] = Counter()
    for salience, c in top:
        weight[c.domain] += salience
    domain = min(weight, key=lambda d: (-weight[d], d)) if weight else None
    theta = state.theta.get(domain, 0.0) if domain else 0.0
    return ExplainInputs(
        mode="paragraph",
        content_id=doc.content_id,
        paragraph_id=para.id,
        span=para.text,
        sentence=para.text,
        paragraph=para.text,
        concepts=concepts,
        band=model.band_of(model.sigmoid(theta)),
        thinks_in=thinks_in,
        style=style,
    )
