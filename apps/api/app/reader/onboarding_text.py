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


# ---------------------------------------------------------------- word-level topic match

# Removed before matching words (Sourabh, 2026-10-11): stop-words, words that say nothing about
# a topic, and bare country names (a place alone doesn't say what the reader follows).
STOP_WORDS = frozenset(
    [
        "a",
        "an",
        "the",
        "and",
        "or",
        "of",
        "in",
        "on",
        "at",
        "to",
        "for",
        "from",
        "with",
        "by",
        "about",
        "into",
        "over",
        "under",
        "after",
        "before",
        "my",
        "our",
        "your",
        "their",
        "his",
        "her",
        "its",
        "this",
        "that",
        "these",
        "those",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "i",
        "me",
        "we",
        "you",
        "it",
        "as",
        "up",
        "out",
        "all",
        "some",
        "any",
        "more",
        "most",
        "other",
        "new",
        "how",
        "what",
        "why",
        "who",
        "which",
    ]
)
GENERIC_WORDS = frozenset(
    [
        "news",
        "latest",
        "update",
        "updates",
        "today",
        "daily",
        "weekly",
        "week",
        "stuff",
        "things",
        "thing",
        "topic",
        "topics",
        "story",
        "stories",
        "current",
        "events",
        "world",
        "global",
        "local",
        "general",
        "info",
        "information",
    ]
)
COUNTRY_NAMES = frozenset(
    [
        "india",
        "china",
        "us",
        "usa",
        "america",
        "uk",
        "britain",
        "england",
        "japan",
        "germany",
        "france",
        "russia",
        "ukraine",
        "pakistan",
        "bangladesh",
        "nepal",
        "sri",
        "lanka",
        "canada",
        "australia",
        "brazil",
        "italy",
        "spain",
        "israel",
        "iran",
        "korea",
        "singapore",
        "indonesia",
        "africa",
        "mexico",
        "turkey",
    ]
)
MIN_WORD_CHARS = 3
_TOKEN = re.compile(r"[a-z0-9][a-z0-9&'’-]*")


def _keep(word: str) -> bool:
    return word not in STOP_WORDS and word not in GENERIC_WORDS and word not in COUNTRY_NAMES


def word_chunks(phrase: str) -> list[tuple[str, int]]:
    """(chunk, words) for every kept word of ≥ 3 chars and every 2-word chunk of kept words
    that were adjacent in the phrase; lowercased, possessives dropped. Order of appearance."""
    words = [re.sub(r"['’]s$", "", w) for w in _TOKEN.findall(phrase.casefold())]
    out: list[tuple[str, int]] = []
    for i, w in enumerate(words):
        if _keep(w) and i + 1 < len(words) and _keep(words[i + 1]):
            out.append((f"{w} {words[i + 1]}", 2))
        if _keep(w) and len(w) >= MIN_WORD_CHARS:
            out.append((w, 1))
    return out


def _forms(chunk: str) -> list[str]:
    """The chunk, and with a plural last word made singular ("black holes" → "black hole")."""
    if len(chunk) > 3 and chunk.endswith("s") and not chunk.endswith("ss"):
        return [chunk, chunk[:-1]]
    return [chunk]


@dataclass(frozen=True)
class WordMatch:
    topic: str
    chunk: str
    via: str  # "alias" or the concept id


def word_topic(graph: ConceptGraph, phrase: str) -> WordMatch | None:
    """Deterministic, no model call: each chunk is looked up in the alias list and in concept
    labels/aliases. A one-word chunk counts as a concept only when the concept was met in the
    corpus (doc_freq > 0; seed-only single words like "Column" are too generic). Strongest wins:
    2-word chunks, then an alias over a concept, then the concept's doc_freq, then the earlier
    chunk."""
    best: tuple[tuple[int, int, int, int], WordMatch] | None = None
    for pos, (chunk, n) in enumerate(word_chunks(phrase)):
        for form in _forms(chunk):
            found: list[tuple[tuple[int, int, int, int], WordMatch]] = []
            if (topic := alias_topic(form)) is not None:
                found.append(((n, 1, 0, -pos), WordMatch(topic, form, "alias")))
            concept = graph.lookup(form)
            if concept is not None and (n == 2 or concept.doc_freq > 0):
                key = (n, 0, concept.doc_freq, -pos)
                found.append((key, WordMatch(concept.domain, form, concept.id)))
            for key, match in found:
                if best is None or key > best[0]:
                    best = (key, match)
    return best[1] if best is not None else None
