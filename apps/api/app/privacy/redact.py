"""Remove personal data from reader-typed text before it reaches a model (DESIGN §11.3).

Emails, phone numbers, card-like digit runs (Luhn-valid), Aadhaar-like 12-digit numbers and
PAN-like ids become placeholders. M8's server-side Presidio backstop wraps this same entry point.
"""

import re

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
_PAN = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")
_AADHAAR = re.compile(r"\b\d{4}[ -]?\d{4}[ -]?\d{4}\b")
_DIGITS = re.compile(r"(?<!\w)(?:\d[ -]?){13,19}(?!\w)")
_PHONE = re.compile(r"(?<!\w)\+?\d[\d ()-]{7,}\d(?!\w)")


def _luhn(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
        alt = not alt
    return total % 10 == 0


def redact(text: str) -> str:
    text = _EMAIL.sub("[email]", text)
    text = _PAN.sub("[id]", text)

    def card(m: re.Match[str]) -> str:
        digits = re.sub(r"\D", "", m.group())
        return "[number]" if 13 <= len(digits) <= 19 and _luhn(digits) else m.group()

    text = _DIGITS.sub(card, text)
    text = _AADHAAR.sub("[id]", text)
    return _PHONE.sub("[phone]", text)
