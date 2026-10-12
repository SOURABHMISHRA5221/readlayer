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
    results = analyzer().analyze(text=text, language=LANG, entities=list(ENTITIES))
    counts = Counter(r.entity_type for r in results if r.score >= _floor(r.entity_type, min_score))
    if placeholders := text.count(PLACEHOLDER):
        counts["CLIENT_REDACTED"] = placeholders
    return Findings(
        words=len(text.split()),
        by_type=dict(sorted(counts.items())),
        client_cards=text.count(f"{PLACEHOLDER}card]"),
    )


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
