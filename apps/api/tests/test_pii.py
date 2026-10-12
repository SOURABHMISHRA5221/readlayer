"""Presidio backstop (M8 §A3): frozen refuse/pass fixtures, offline build, counts-only logs."""

import json
import logging
import subprocess
import sys
from pathlib import Path

import pytest

from app.privacy import pii
from app.privacy.redact import redact

PAGES = json.loads((Path(__file__).parent / "fixtures" / "pii_pages.json").read_text())


@pytest.mark.parametrize("page", PAGES["refuse"], ids=lambda p: p["name"])
def test_personal_data_pages_are_refused(page):
    assert pii.scan(page["paragraphs"]).refuse


@pytest.mark.parametrize("page", PAGES["refuse"], ids=lambda p: p["name"])
def test_still_refused_after_the_clients_redaction(page):
    redacted = [redact(p) for p in page["paragraphs"]]
    findings = pii.scan(redacted)
    assert findings.refuse and findings.by_type["CLIENT_REDACTED"] > 0


@pytest.mark.parametrize("page", PAGES["pass"], ids=lambda p: p["name"])
def test_news_pages_pass(page):
    assert not pii.scan(page["paragraphs"]).refuse


def test_a_single_phone_in_a_short_page_never_refuses():
    findings = pii.Findings(words=80, by_type={"PHONE_NUMBER": 2})
    assert findings.per_1000_words > pii.MAX_PER_1000_WORDS and not findings.refuse


def test_three_cards_refuse_at_any_length():
    assert pii.Findings(words=5000, by_type={}, client_cards=3).refuse


def test_logs_carry_counts_only(caplog):
    page = PAGES["refuse"][0]["paragraphs"]
    with caplog.at_level(logging.INFO, logger="app.privacy"):
        pii.check(page)
    (record,) = [r for r in caplog.records if r.getMessage() == "pii backstop"]
    assert record.pii_counts and record.refused is True
    assert "98201" not in caplog.text and "@" not in caplog.text


OFFLINE_BUILD = """
import socket, sys
attempts = []
def refuse(*a, **k):
    attempts.append(a[1:2])
    raise OSError("network disabled in this test")
socket.socket.connect = refuse
socket.create_connection = refuse
socket.getaddrinfo = refuse
from app.privacy import pii
f = pii.scan(["Write to tips@newsroom.co.in or call +91 98201 44312 tonight."])
import tldextract.tldextract as tx
assert tx.TLD_EXTRACTOR.suffix_list_urls == (), tx.TLD_EXTRACTOR.suffix_list_urls
assert f.by_type.get("EMAIL_ADDRESS") == 1, f.by_type
assert attempts == [], attempts  # tldextract falls back silently, so count the tries
print("ok")
"""


def test_the_analyzer_builds_and_runs_with_sockets_blocked():
    out = subprocess.run(
        [sys.executable, "-c", OFFLINE_BUILD],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert out.returncode == 0 and out.stdout.strip() == "ok", out.stderr[-2000:]


def test_no_analyze_call_gets_more_than_a_chunk(monkeypatch):
    engine = pii.analyzer()
    sizes: list[int] = []
    real = engine.analyze

    def spy(text, **kw):
        sizes.append(len(text))
        return real(text=text, **kw)

    monkeypatch.setattr(engine, "analyze", spy)
    long = ("Bond yields fell three basis points as markets priced a long pause. " * 80).strip()
    pii.scan([long] * 30)  # ~160k chars, paragraphs longer than nothing special
    assert sizes and max(sizes) <= pii.CHUNK_CHARS


def test_chunks_keep_every_word_and_cut_long_paragraphs_at_spaces():
    paras = ["word " * 3000, "short paragraph here", "x" * 25_000]
    out = pii.chunks([p.strip() for p in paras], size=10_000)
    assert all(len(c) <= 10_000 for c in out)
    assert "".join(out).replace("\n", "").replace(" ", "") == "".join(paras).replace(" ", "")


def test_the_parser_and_ner_are_off():
    names = next(iter(pii.analyzer().nlp_engine.nlp.values())).pipe_names
    assert "parser" not in names and "ner" not in names and "lemmatizer" in names
