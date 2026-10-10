"""Recommendations from our own corpus: no API calls, pure over docs + the concept graph.

Relations (each candidate names the concepts that triggered it):
- same_story: the same story from another source (syndicated text, or the same event:
  overlapping headline words and concepts within a few days);
- primer: an article that explains, in its own text, a weak prerequisite of a concept that
  was new to this reader (Wikipedia explainers preferred);
- deeper: an article centred on a concept that builds on one the reader just met;
- angle: the same core concepts from a different source or country.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

from app.graph.build import jaccard, normalize_label, shingles
from app.graph.graph import ConceptGraph
from app.ingest.models import ContentDoc
from app.reader.model import prior
from app.recs.models import Relation

WIKIPEDIA_SITE = "Wikimedia Foundation, Inc."
SOURCE_COUNTRY = {
    "BBC News": "the UK",
    "The Guardian": "the UK",
    "Mint": "India",
    "The Economic Times": "India",
    "BusinessLine": "India",
    "Business Standard": "India",
    "The Hindu": "India",
}

SYNDICATED_JACCARD = 0.5
SAME_EVENT_TITLE_JACCARD = 0.3
SAME_EVENT_CONCEPT_JACCARD = 0.2
SAME_EVENT_DAYS = 4
WEAK_PRIOR = 0.6
DEEPER_MIN_SALIENCE = 0.6
CORE_CONCEPTS = 5
ANGLE_MIN_OVERLAP = 0.4
ANGLE_COUNTRY_BOOST = 1.15
NON_WIKI_PRIMER = 0.7
PER_RELATION_LIMIT = 6

_STOP_WORDS = (
    "a an and are as at be by for from has have in into is it its of on or that the this to "
    "was were will with after over amid says say said new how why what"
)
_STOP = frozenset(_STOP_WORDS.split())


@dataclass(frozen=True)
class LibraryCandidate:
    content_id: str
    relation: Relation
    relevance: float  # 0..1
    trigger_ids: tuple[str, ...]
    detail: str | None = None  # primer: the prerequisite; deeper: the next concept; angle: who


@dataclass
class LibraryIndex:
    """Derived once per catalog version: concepts per doc, docs per concept, text shingles."""

    docs: dict[str, ContentDoc]
    concepts: dict[str, dict[str, tuple[float, bool]]]  # doc → concept → (salience, explained)
    by_concept: dict[str, list[str]]
    _shingles: dict[str, set[str]] = field(default_factory=dict)

    @classmethod
    def build(cls, docs: Sequence[ContentDoc]) -> "LibraryIndex":
        concepts: dict[str, dict[str, tuple[float, bool]]] = {}
        by_concept: dict[str, list[str]] = {}
        for doc in docs:
            seen: dict[str, tuple[float, bool]] = {}
            for d in doc.demands:
                if not d.target_id:
                    continue
                sal, explained = seen.get(d.target_id, (0.0, False))
                seen[d.target_id] = (max(sal, d.salience), explained or d.explained_in_text)
            concepts[doc.content_id] = seen
            for cid in seen:
                by_concept.setdefault(cid, []).append(doc.content_id)
        return cls({d.content_id: d for d in docs}, concepts, by_concept)

    def shingles(self, content_id: str) -> set[str]:
        if content_id not in self._shingles:
            doc = self.docs[content_id]
            self._shingles[content_id] = shingles(" ".join(p.text for p in doc.paragraphs))
        return self._shingles[content_id]


def is_wikipedia(doc: ContentDoc) -> bool:
    return doc.site == WIKIPEDIA_SITE or "wikipedia.org" in doc.url


def title_words(title: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", title.casefold()) if w not in _STOP and len(w) > 2}


def _day(value: str | None) -> date | None:
    try:
        return date.fromisoformat((value or "")[:10])
    except ValueError:
        return None


def same_story(index: LibraryIndex, doc: ContentDoc, triggers: set[str]) -> list[LibraryCandidate]:
    mine = index.concepts[doc.content_id]
    words = title_words(doc.title)
    when = _day(doc.published)
    out = []
    for other in index.docs.values():
        if other.content_id == doc.content_id or is_wikipedia(other) or other.url == doc.url:
            continue
        theirs = index.concepts[other.content_id]
        shared = set(mine) & set(theirs)
        concept_overlap = jaccard(set(mine), set(theirs))
        if (
            jaccard(index.shingles(doc.content_id), index.shingles(other.content_id))
            >= SYNDICATED_JACCARD
        ):
            relevance = 1.0
        elif (
            other.site != doc.site
            and jaccard(words, title_words(other.title)) >= SAME_EVENT_TITLE_JACCARD
            and concept_overlap >= SAME_EVENT_CONCEPT_JACCARD
            and (
                when is None
                or (d := _day(other.published)) is None
                or abs((when - d).days) <= SAME_EVENT_DAYS
            )
        ):
            relevance = 0.5 + 0.5 * concept_overlap
        else:
            continue
        out.append(
            LibraryCandidate(
                other.content_id,
                "same_story",
                relevance,
                tuple(sorted(shared & triggers)),
                other.site,
            )
        )
    return out


def primers(
    index: LibraryIndex,
    doc: ContentDoc,
    graph: ConceptGraph,
    theta: Mapping[str, float],
    triggers: Sequence[str],
) -> list[LibraryCandidate]:
    out = []
    for cid in triggers:
        concept = graph.get(cid)
        if concept is None:
            continue
        weak = [
            q
            for q in graph.prerequisites(cid)
            if prior(theta.get(q.domain, 0.0), q.base_difficulty) < WEAK_PRIOR
        ]
        for target in weak or [concept]:
            names = {normalize_label(target.label), *(normalize_label(a) for a in target.aliases)}
            for other_id in index.by_concept.get(target.id, []):
                if other_id == doc.content_id:
                    continue
                salience, explained = index.concepts[other_id][target.id]
                other = index.docs[other_id]
                wiki = is_wikipedia(other)
                topic = normalize_label(other.title.split(" - ")[0])
                if wiki and topic in names:
                    relevance = 1.0  # the encyclopedia article *about* this concept
                elif wiki and salience >= 0.7:
                    relevance = 0.8 * salience
                elif explained:
                    relevance = NON_WIKI_PRIMER * salience
                else:
                    continue
                out.append(LibraryCandidate(other_id, "primer", relevance, (cid,), target.label))
    return out


def deeper(
    index: LibraryIndex, doc: ContentDoc, graph: ConceptGraph, triggers: Sequence[str]
) -> list[LibraryCandidate]:
    out = []
    for cid in triggers:
        for nxt in graph.dependents(cid):
            for other_id in index.by_concept.get(nxt.id, []):
                if other_id == doc.content_id:
                    continue
                salience, _ = index.concepts[other_id][nxt.id]
                if salience >= DEEPER_MIN_SALIENCE:
                    out.append(
                        LibraryCandidate(other_id, "deeper", 0.9 * salience, (cid,), nxt.label)
                    )
    return out


def angles(index: LibraryIndex, doc: ContentDoc, triggers: set[str]) -> list[LibraryCandidate]:
    mine = index.concepts[doc.content_id]
    core = {c for c, _ in sorted(mine.items(), key=lambda kv: -kv[1][0])[:CORE_CONCEPTS]}
    if len(core) < 2:
        return []
    my_country = SOURCE_COUNTRY.get(doc.site)
    out = []
    for other in index.docs.values():
        if other.content_id == doc.content_id or other.site == doc.site or is_wikipedia(other):
            continue
        shared = core & set(index.concepts[other.content_id])
        overlap = len(shared) / len(core)
        if overlap < ANGLE_MIN_OVERLAP:
            continue
        country = SOURCE_COUNTRY.get(other.site)
        boosted = country is not None and my_country is not None and country != my_country
        relevance = min(1.0, overlap * (ANGLE_COUNTRY_BOOST if boosted else 1.0))
        detail = country if boosted else other.site
        trig = tuple(sorted(shared & triggers)) or tuple(sorted(shared))[:2]
        out.append(LibraryCandidate(other.content_id, "angle", relevance, trig, detail))
    return out


def library_candidates(
    index: LibraryIndex,
    doc: ContentDoc,
    graph: ConceptGraph,
    theta: Mapping[str, float],
    triggers: Sequence[str],
    hidden: frozenset[str] = frozenset(),
) -> list[LibraryCandidate]:
    """Best candidate per (relation, doc), at most PER_RELATION_LIMIT per relation. `hidden`
    (other readers' pages) is dropped before the cut, so it never takes this reader's slots."""
    trigger_set = set(triggers)
    groups = [
        same_story(index, doc, trigger_set),
        primers(index, doc, graph, theta, triggers),
        deeper(index, doc, graph, triggers),
        angles(index, doc, trigger_set),
    ]
    out: list[LibraryCandidate] = []
    for group in groups:
        best: dict[str, LibraryCandidate] = {}
        for c in group:
            if c.content_id in hidden:
                continue
            if c.content_id not in best or c.relevance > best[c.content_id].relevance:
                best[c.content_id] = c
        ranked = sorted(best.values(), key=lambda c: (-c.relevance, c.content_id))
        out.extend(ranked[:PER_RELATION_LIMIT])
    return out
