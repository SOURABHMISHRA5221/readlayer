"""CPU-only text features: word frequency (wordfreq) and syntactic structure (spaCy)."""

import logging
import time
from functools import lru_cache

import spacy
from spacy.language import Language
from spacy.tokens import Token
from wordfreq import zipf_frequency

log = logging.getLogger("app.ingest")

# Normalisers for parse_structure; values at or above these count as maximally dense.
MAX_PARSE_DEPTH = 12
MAX_SENTENCE_TOKENS = 40


def zipf(text: str) -> float:
    return round(zipf_frequency(text, "en"), 2)


@lru_cache
def _nlp() -> Language:
    """Loaded on the first new article, not at startup, so cold starts stay short."""
    start = time.perf_counter()
    nlp = spacy.load("en_core_web_sm", disable=["ner", "lemmatizer"])
    log.info("spacy loaded", extra={"load_ms": round((time.perf_counter() - start) * 1000, 1)})
    return nlp


def _depth(token: Token) -> int:
    depth = 0
    while token.head.i != token.i:  # spaCy builds a new Token per access; compare indices
        token = token.head
        depth += 1
    return depth


def parse_structure(text: str) -> float:
    """0.5·normalised max parse depth + 0.5·normalised mean sentence length, in [0, 1]."""
    doc = _nlp()(text)
    sentences = [s for s in doc.sents if any(not t.is_punct for t in s)]
    if not sentences:
        return 0.0
    max_depth = max(_depth(t) for t in doc)
    mean_len = sum(len(s) for s in sentences) / len(sentences)
    score = 0.5 * min(1.0, max_depth / MAX_PARSE_DEPTH) + 0.5 * min(
        1.0, mean_len / MAX_SENTENCE_TOKENS
    )
    return round(score, 3)


def structure(parse_score: float, llm_flag: bool) -> float:
    """DESIGN §3: 0.5·parse + 0.5·LLM flag."""
    return round(0.5 * parse_score + 0.5 * (1.0 if llm_flag else 0.0), 3)
