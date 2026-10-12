"""Server-side PII backstop for extension text (M8 §A3, DESIGN §11.3).

The extension redacts before sending (`redact.ts`); this catches a page that is mostly personal
data anyway (a contact page, a donor list) and refuses it, before anything is stored. Below the
threshold the strict redactor runs on every paragraph (`service.submitted_texts`).

Presidio with the spaCy model already in the image, only the recognizers we need (email, phone,
card, IBAN, Aadhaar with its checksum, PAN). Imported lazily from the ingestion path, so read
paths and cold starts never load it; built once per process. Offline: tldextract (used by the
email recognizer) reads its bundled suffix-list snapshot and never downloads one.

Thresholds come from evidence (decision 26): `scripts/measure_pii.py` over the stored corpus and
the frozen fixtures in tests/fixtures/pii_pages.json; numbers in docs/STATUS.md §22.
"""

import logging
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

log = logging.getLogger("app.privacy")

LANG = "en"
PHONE_REGIONS = ("IN", "US", "GB")
ENTITIES = ("EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD", "IBAN_CODE", "IN_AADHAAR", "IN_PAN")
# Set from scripts/measure_pii.py (see the module docstring). A finding counts at MIN_SCORE or
# more; phones at 0.4, the score Presidio's phone recognizer gives every match. Below 0.5, PAN
# hits are its catch-all pattern (any 10-character token with 4 digits) lifted by context words.
MIN_SCORE = 0.5
MIN_SCORES = {"PHONE_NUMBER": 0.4}
# 2026-10-12, 338 stored articles: max 3.98 per 1,000 words (journalists' contact emails), 34
# with any finding, at most 1 card number; frozen refuse fixtures 79 and 110, pass fixtures at
# most 6.9. Refuse above 20 (5x the corpus max), and never on fewer than 3 findings.
MAX_PER_1000_WORDS = 20.0
MIN_FINDINGS = 3
MAX_CARDS = 3
PLACEHOLDER = "[REDACTED:"
# Bounded work per analyze call: spaCy's cost grows faster than the text (150k chars in one call
# took 29.6 s and 717 MB), so pages are scanned in chunks of at most this many characters.
CHUNK_CHARS = 10_000
# Recognizers here are patterns plus context words (lemmas): the parser and NER aren't used.
UNUSED_PIPES = ("parser", "ner")


@dataclass(frozen=True)
class Findings:
    words: int
    by_type: dict[str, int]
    client_cards: int = 0

    @property
    def total(self) -> int:
        return sum(self.by_type.values())

    @property
    def per_1000_words(self) -> float:
        return 1000 * self.total / max(1, self.words)

    @property
    def refuse(self) -> bool:
        dense = self.total >= MIN_FINDINGS and self.per_1000_words > MAX_PER_1000_WORDS
        cards = self.by_type.get("CREDIT_CARD", 0) + self.client_cards
        return dense or cards >= MAX_CARDS


def _offline_tldextract() -> None:
    import tldextract.tldextract as tx

    tx.TLD_EXTRACTOR = tx.TLDExtract(suffix_list_urls=(), cache_dir=None, fallback_to_snapshot=True)


@lru_cache(maxsize=1)
def analyzer() -> Any:
    _offline_tldextract()
    from presidio_analyzer import AnalyzerEngine, RecognizerRegistry
    from presidio_analyzer.nlp_engine import NlpEngineProvider
    from presidio_analyzer.predefined_recognizers import (
        CreditCardRecognizer,
        EmailRecognizer,
        IbanRecognizer,
        InAadhaarRecognizer,
        InPanRecognizer,
        PhoneRecognizer,
    )

    nlp = NlpEngineProvider(
        nlp_configuration={
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": LANG, "model_name": "en_core_web_sm"}],
        }
    ).create_engine()
    for model in nlp.nlp.values():
        model.select_pipes(disable=[p for p in UNUSED_PIPES if p in model.pipe_names])
    registry = RecognizerRegistry(supported_languages=[LANG])
    for recognizer in (
        EmailRecognizer(),
        PhoneRecognizer(supported_regions=PHONE_REGIONS),
        CreditCardRecognizer(),
        IbanRecognizer(),
        InAadhaarRecognizer(),
        InPanRecognizer(),
    ):
        registry.add_recognizer(recognizer)
    return AnalyzerEngine(nlp_engine=nlp, registry=registry, supported_languages=[LANG])


def scan(paragraphs: list[str], min_score: float | None = None) -> Findings:
    """Findings per entity type over the whole page. Never returns or logs matched text.
    Placeholders the client already put in (`[REDACTED:type]`) count too, as CLIENT_REDACTED:
    a contact page is still a contact page after the extension redacted it.
    `min_score` replaces the per-type floors (measurement only)."""
    text = "\n\n".join(paragraphs)
    engine = analyzer()
    counts: Counter[str] = Counter()
    for chunk in chunks(paragraphs):
        results = engine.analyze(text=chunk, language=LANG, entities=list(ENTITIES))
        counts.update(r.entity_type for r in results if r.score >= _floor(r.entity_type, min_score))
    if placeholders := text.count(PLACEHOLDER):
        counts["CLIENT_REDACTED"] = placeholders
    return Findings(
        words=len(text.split()),
        by_type=dict(sorted(counts.items())),
        client_cards=text.count(f"{PLACEHOLDER}card]"),
    )


def chunks(paragraphs: list[str], size: int = CHUNK_CHARS) -> list[str]:
    """Paragraphs packed into chunks of at most `size` characters; a longer paragraph is cut at
    whitespace (a finding split by a cut is lost: rare, and the strict redactor runs anyway)."""
    out: list[str] = []
    current = ""
    for para in paragraphs:
        if len(para) > size and current:  # keep page order: flush before cutting a long one
            out.append(current)
            current = ""
        while len(para) > size:
            cut = para.rfind(" ", 0, size)
            cut = cut if cut > 0 else size
            out.append(para[:cut])
            para = para[cut:].lstrip()
        if current and len(current) + 2 + len(para) > size:
            out.append(current)
            current = ""
        current = f"{current}\n\n{para}" if current else para
    if current:
        out.append(current)
    return out


def _floor(entity: str, override: float | None) -> float:
    return override if override is not None else MIN_SCORES.get(entity, MIN_SCORE)


def check(paragraphs: list[str]) -> Findings:
    """Scan and log counts only (DESIGN §11.3: never the matched text)."""
    findings = scan(paragraphs)
    log.info(
        "pii backstop",
        extra={
            "pii_counts": findings.by_type,
            "words": findings.words,
            "refused": findings.refuse,
        },
    )
    return findings
