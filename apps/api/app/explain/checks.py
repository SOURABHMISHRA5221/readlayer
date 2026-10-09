"""Deterministic faithfulness checks on `author_says` (DESIGN §7 verifier, step 1). Pure.

Scope: in span mode hedges, attribution and negation are checked against the span's sentence
(a hedge elsewhere in the paragraph says nothing about this restatement); numbers against the
whole paragraph. Paragraph mode, the stricter one, checks all four against the paragraph.
Each failure is a short reason, fed back to the generator on the retry.
"""

import re
from dataclasses import dataclass

from app.explain.inputs import ExplainInputs

HEDGES = frozenset(
    {
        "may", "might", "could", "would", "likely", "unlikely", "possibly", "possible", "perhaps",
        "probably", "reportedly", "alleged", "allegedly", "expected", "expects", "expect",
        "appears", "appear", "appeared", "seems", "seem", "seemed", "suggests", "suggest",
        "suggested", "estimated", "estimates", "estimate", "potentially", "potential",
        "projected", "forecast", "forecasts", "uncertain", "unclear", "believed",
    }
)  # fmt: skip
# Nouns that look like attribution ("bonds or notes", "news reports", "in view of") are left
# out: they would demand an attribution the source doesn't make.
ATTRIBUTION = frozenset(
    {
        "said", "says", "say", "argues", "argued", "argue", "claims", "claimed", "claim",
        "told", "stated", "states", "noted", "wrote", "writes", "believes", "believe",
        "thinks", "think", "warned", "warns", "reported", "announced", "added",
        "insists", "insisted", "contends", "contended", "according", "acknowledged", "admits",
        "admitted", "maintains", "maintained", "predicts", "predicted", "opinion", "theorize",
        "theorise", "considered", "declared",
        "arguably", "critics", "supporters", "analysts", "economists", "officials",
    }
)  # fmt: skip
NEGATIONS = frozenset(
    {"not", "no", "never", "none", "neither", "nor", "nothing", "nobody", "cannot", "without",
     "unlikely", "fails", "failed", "fail"}
)  # fmt: skip
NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20,
    "thirty": 30, "forty": 40, "fifty": 50, "hundred": 100, "half": 0.5, "dozen": 12,
}  # fmt: skip
SCALES = {
    "thousand": 1e3, "k": 1e3, "million": 1e6, "mn": 1e6, "m": 1e6, "billion": 1e9, "bn": 1e9,
    "b": 1e9, "trillion": 1e12, "tn": 1e12, "lakh": 1e5, "lakhs": 1e5, "crore": 1e7,
    "crores": 1e7,
}  # fmt: skip
_WORD = re.compile(r"[a-z]+(?:'[a-z]+)?")
_NUMBER = re.compile(
    r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?\s*"
    r"(%|per\s?cent\b|percent\b|percentage points?\b|bps\b|basis points?\b|"
    r"thousand\b|million\b|billion\b|trillion\b|lakhs?\b|crores?\b|mn\b|bn\b|tn\b|k\b|m\b|b\b)?",
    re.IGNORECASE,
)
_URL = re.compile(r"https?://|www\.|\b[a-z0-9-]+\.(?:com|net|org|io|xyz|ru|info)\b", re.I)


@dataclass(frozen=True)
class Num:
    value: float
    kind: str  # "%", "pp", "bps" or ""


def words(text: str) -> list[str]:
    return _WORD.findall(text.lower().replace("’", "'"))


# Words that are usually not quantities in a restatement ("one of the banks", "half-way").
_LOOSE_WORDS = frozenset({"zero", "one", "half"})


def numbers(text: str, *, loose_words: bool = True) -> list[Num]:
    """Numbers with units normalised: "40%" = "40 per cent", "3.5bn" = "3.5 billion".
    `loose_words=False` skips number words that are usually pronouns or idioms."""
    out: list[Num] = []
    for m in _NUMBER.finditer(text):
        value = float(m.group(1).replace(",", "") + (m.group(2) or ""))
        unit = re.sub(r"\s+", " ", (m.group(3) or "").lower())
        if unit in ("%", "per cent", "percent"):
            out.append(Num(value, "%"))
        elif unit.startswith("percentage point"):
            out.append(Num(value, "pp"))
        elif unit in ("bps", "basis point", "basis points"):
            out.append(Num(value, "bps"))
        else:
            out.append(Num(value * SCALES.get(unit, 1.0), ""))
    for w in words(text):
        if w in NUMBER_WORDS and (loose_words or w not in _LOOSE_WORDS):
            out.append(Num(float(NUMBER_WORDS[w]), ""))
    return out


def _same(a: Num, b: Num) -> bool:
    kinds_ok = a.kind == b.kind or (a.kind in ("%", "pp") and b.kind in ("%", "pp"))
    return kinds_ok and abs(a.value - b.value) <= 1e-9 * max(1.0, abs(a.value))


def _has_negation(text: str) -> bool:
    ws = words(text)
    return any(w in NEGATIONS or w.endswith("n't") for w in ws)


def _has(text: str, vocab: frozenset[str]) -> bool:
    return any(w in vocab for w in words(text))


def check(inputs: ExplainInputs, author_says: str, background: str = "") -> list[str]:
    """Reasons the restatement is unfaithful; empty when every check passes."""
    reasons: list[str] = []
    scope = inputs.paragraph if inputs.mode == "paragraph" else inputs.sentence
    source_nums = numbers(inputs.paragraph)
    for n in numbers(author_says, loose_words=False):
        if not any(_same(n, s) for s in source_nums):
            shown = f"{n.value:g}{n.kind}"
            reasons.append(f"number_not_in_source: {shown} does not appear in the source")
    if _has(scope, HEDGES) and not _has(author_says, HEDGES):
        reasons.append("hedge_dropped: the source is hedged (may/could/expected/...); keep it")
    if _has(scope, ATTRIBUTION) and not _has(author_says, ATTRIBUTION):
        reasons.append(
            "attribution_dropped: the source attributes this view (said/according to/...); "
            "say who holds it"
        )
    if _has_negation(scope) and not _has_negation(author_says):
        reasons.append("negation_dropped: the source contains a negation; keep it")
    for field, text in (("author_says", author_says), ("background", background)):
        if _URL.search(text) and not _URL.search(inputs.paragraph):
            reasons.append(f"link_in_{field}: links that are not in the source are not allowed")
    return reasons
