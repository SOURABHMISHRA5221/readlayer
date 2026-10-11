"""Onboarding free text → concepts and topics (decisions 41, 42; DESIGN §4, §11). Pure: no I/O.

The reader may type what else they follow ("F1, startups"). The text is redacted, split on
commas into at most MAX_PIECES pieces of at most MAX_PIECE_CHARS, and each piece is matched:
exact concept label/alias first (whole, then its " and " parts), then the topic alias list
below, then (in the route) `resolve_names` and the nearest topic scope line by embedding.
Nothing of the text is stored or logged, and it never reaches search.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.graph.graph import ConceptGraph
from app.graph.models import Concept
from app.graph.taxonomy import TAXONOMY

MAX_TEXT_CHARS = 120
MAX_PIECES = 5
MAX_PIECE_CHARS = 40

# Casefolded exact phrase → taxonomy domain, every topic covered. No model call on this path
# (decision 42). Common phrases only; never copied from evals/cases/onboarding_topics.yaml
# except "smartphones" and "mutual funds", which Sourabh named (2026-10-11).
_ALIASES_BY_TOPIC: Mapping[str, tuple[str, ...]] = {
    "sports": ("f1", "formula 1", "formula one", "motorsport", "ipl", "cricket", "test cricket",
               "football", "soccer", "premier league", "champions league", "la liga", "fifa",
               "nba", "nfl", "tennis", "badminton", "kabaddi", "olympics", "chess"),
    "technology": ("ai", "artificial intelligence", "llms", "llm", "generative ai", "chatgpt",
                   "tech", "gadgets", "smartphones", "coding", "programming", "cybersecurity",
                   "evs", "electric vehicles", "semiconductors"),
    "finance": ("crypto", "cryptocurrency", "bitcoin", "stock market", "stocks", "sensex",
                "nifty", "mutual funds", "investing", "trading", "personal finance"),
    "business": ("startups", "startup", "vc", "venture capital", "entrepreneurship",
                 "business news", "marketing"),
    "economics": ("economy", "indian economy", "gdp", "macroeconomics"),
    "policy": ("gst", "income tax", "taxes", "public policy", "government schemes"),
    "politics": ("elections", "indian politics", "us politics", "world politics",
                 "geopolitics", "lok sabha"),
    "law": ("supreme court", "high court", "constitution", "legal news"),
    "science": ("space", "isro", "nasa", "astronomy", "physics", "biology", "chemistry"),
    "health": ("mental health", "fitness", "nutrition", "diet", "yoga", "medicine", "covid"),
    "environment": ("climate", "climate change", "global warming", "pollution", "wildlife"),
    "culture": ("movies", "films", "cinema", "bollywood", "books", "music", "art", "anime"),
    "education": ("upsc", "jee", "neet", "exams", "higher education", "edtech"),
    "society": ("religion", "gender", "migration", "social issues"),
}  # fmt: skip
ONBOARDING_TOPIC_ALIASES: Mapping[str, str] = {
    phrase: topic for topic, phrases in _ALIASES_BY_TOPIC.items() for phrase in phrases
}

_SPACES = re.compile(r"\s+")
_AND = re.compile(r"\s+and\s+|\s*&\s*", re.IGNORECASE)


def pieces(redacted: str) -> list[str]:
    """Comma-separated pieces of already-redacted text: trimmed, non-empty, de-duplicated
    (casefold), at most MAX_PIECES, each cut to MAX_PIECE_CHARS on a word boundary."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in redacted.split(","):
        piece = _SPACES.sub(" ", raw).strip(" .;:!?\"'")
        if len(piece) > MAX_PIECE_CHARS:
            piece = piece[:MAX_PIECE_CHARS].rsplit(" ", 1)[0] or piece[:MAX_PIECE_CHARS]
        if piece and piece.casefold() not in seen:
            seen.add(piece.casefold())
            out.append(piece)
        if len(out) == MAX_PIECES:
            break
    return out


def alias_topic(phrase: str) -> str | None:
    return ONBOARDING_TOPIC_ALIASES.get(_SPACES.sub(" ", phrase).strip().casefold())


@dataclass(frozen=True)
class ExactMatch:
    concepts: tuple[Concept, ...]  # found by exact label/alias
    rest: tuple[str, ...]  # phrases still to match (the whole piece, or its unmatched parts)


def exact_match(graph: ConceptGraph, piece: str) -> ExactMatch:
    """The whole piece first ("mergers and acquisitions" is one concept); only on a miss is it
    split on " and " / "&". If no part matches either, the whole piece goes on unchanged."""
    hit = graph.lookup(piece)
    if hit is not None:
        return ExactMatch((hit,), ())
    parts = [p.strip() for p in _AND.split(piece) if p.strip()]
    if len(parts) < 2:
        return ExactMatch((), (piece,))
    hits = [(p, graph.lookup(p)) for p in parts]
    found = tuple(c for _, c in hits if c is not None)
    if not found:
        return ExactMatch((), (piece,))
    return ExactMatch(found, tuple(p for p, c in hits if c is None))


def topic_texts() -> list[str]:
    """What each topic is embedded as: its label and one-line scope (taxonomy order)."""
    return [f"{d.label}: {d.scope}" for d in TAXONOMY]


def nearest_topic(
    vector: Sequence[float], topic_vectors: Sequence[Sequence[float]], threshold: float
) -> tuple[str, float] | None:
    """The topic whose scope vector is closest (vectors are L2-normalised, so the dot product is
    the cosine), if it reaches `threshold`. Ties go to the earlier topic."""
    best: tuple[str, float] | None = None
    for info, tv in zip(TAXONOMY, topic_vectors, strict=True):
        score = sum(a * b for a, b in zip(vector, tv, strict=True))
        if best is None or score > best[1]:
            best = (info.id, score)
    return best if best is not None and best[1] >= threshold else None
