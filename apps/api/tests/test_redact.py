"""Redaction (DESIGN §11.3): shared cases with the extension's redact.ts."""

import json
from pathlib import Path

import pytest

from app.privacy.redact import redact

CASES = json.loads((Path(__file__).parent / "fixtures" / "redaction.json").read_text())


@pytest.mark.parametrize("case", CASES["redact"], ids=lambda c: c["in"][:30])
def test_contact_data_is_redacted(case):
    assert redact(case["in"]) == case["out"]


@pytest.mark.parametrize("text", CASES["unchanged"], ids=lambda t: t[:30])
def test_news_text_is_left_alone(text):
    assert redact(text) == text


@pytest.mark.parametrize("text", ["Call 415-555-0132 now", "or 020 7946 0958 at home"])
def test_typed_text_keeps_the_broad_phone_catch(text):
    assert redact(text) == text  # article text: no phone shape, left alone
    assert "[REDACTED:phone]" in redact(text, typed=True) and not any(
        ch.isdigit() for ch in redact(text, typed=True)
    )


def test_typed_mode_still_applies_the_shaped_patterns():
    assert redact("mail sam@x.com", typed=True) == "mail [REDACTED:email]"
