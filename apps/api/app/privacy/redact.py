"""Remove personal data from text before it reaches a model or our store (DESIGN §11.3).

Emails, phone numbers, card numbers (Luhn-valid), Aadhaar numbers (4-4-4 groups) and PAN ids
become `[REDACTED:type]`. The patterns need a real shape, not just a run of digits, so news
figures, dates and year ranges survive (shared cases: tests/fixtures/redaction.json, also used by
the extension's redact.ts). M8's Presidio backstop (app/privacy/pii.py) runs on top of this.

Reader-typed text (profile edits, goals, onboarding) is redacted with `typed=True`: the shaped
patterns, then a broad catch for any digit run that could be a phone number ("415-555-0132",
"020 7946 0958"). A reader typing a figure loses little; article text must keep its figures.
"""

import re
from collections.abc import Callable

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PAN = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")
# Cards: 13–19 digits, grouped by single spaces/dashes or not at all; checked with Luhn. An
# ungrouped run also needs an issuer prefix (Visa 4, Mastercard 51–55 / 22–27, Amex 34/37,
# Discover and RuPay 6, RuPay 81/82), so a 14-digit timestamp like 20081024060408 survives.
_CARD = re.compile(
    r"(?<![\w,.])(?:\d{4}[ -]){3}\d{1,7}(?![\w,.])"
    r"|(?<![\w,.])(?:4|5[1-5]|2[2-7]|3[47]|6|8[12])\d{11,17}(?![\w,.])"
)
# Aadhaar: 12 digits printed as 4-4-4 groups with spaces (dashes would catch "2019-2020-2021").
_AADHAAR = re.compile(r"(?<![\d,.])(?<!\d )[2-9]\d{3} \d{4} \d{4}(?! ?\d)(?![,.]\d)")
# Phones: an international number (+country code), an Indian mobile (10 digits from 6–9,
# optional leading 0), or a landline with a bracketed area code.
_PHONE = re.compile(
    r"\+\d{1,3}(?:[ -]?\(?\d{1,5}\)?){2,5}"
    r"|(?<![\d,.])0?[6-9]\d{4}[ -]?\d{5}(?!\d|[,.]\d)"
    r"|\(0?\d{2,4}\)[ -]?\d{3,4}[ -]?\d{3,4}(?!\d|[,.]\d)"
)
# Typed text only: any 9+ character run of digits and phone punctuation, as before M8.
_PHONE_BROAD = re.compile(r"(?<!\w)\+?\d[\d ()-]{7,}\d(?!\w)")


def _luhn(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
        alt = not alt
    return total % 10 == 0


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def _sub(pattern: re.Pattern[str], kind: str, keep: Callable[[str], bool] | None = None):
    def repl(m: re.Match[str]) -> str:
        return m.group() if keep and keep(m.group()) else f"[REDACTED:{kind}]"

    return lambda text: pattern.sub(repl, text)


def _not_card(match: str) -> bool:
    d = _digits(match)
    return not (13 <= len(d) <= 19 and _luhn(d))


def _not_phone(match: str) -> bool:
    return not 8 <= len(_digits(match)) <= 15


_STEPS = (
    _sub(_EMAIL, "email"),
    _sub(_PAN, "pan"),
    _sub(_CARD, "card", _not_card),
    _sub(_AADHAAR, "aadhaar"),
    _sub(_PHONE, "phone", _not_phone),
)

_TYPED = _sub(_PHONE_BROAD, "phone")


def redact(text: str, typed: bool = False) -> str:
    for step in _STEPS:
        text = step(text)
    return _TYPED(text) if typed else text


def count_redactions(text: str) -> int:
    """Placeholders `redact` adds: personal data still in `text` (existing ones don't count)."""
    return redact(text).count("[REDACTED:") - text.count("[REDACTED:")
