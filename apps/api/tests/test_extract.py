from pathlib import Path

from app.ingest.extract import build_paragraphs, clean_paragraphs, extract
from app.ingest.features import parse_structure, structure, zipf
from app.ingest.urls import normalize_url, url_hash

FIXTURE = (Path(__file__).parent / "fixtures" / "article_business.html").read_text()
URL = "https://news.example/rbi"


def test_extract_title_and_body_without_boilerplate():
    e = extract(FIXTURE, URL)
    assert e.title == "RBI holds repo rate at 6.5% as inflation cools"
    assert e.site == "Example Business Daily"
    body = "\n".join(e.paragraphs)
    assert e.paragraphs[0].startswith("The Reserve Bank of India kept its repo rate")
    for junk in ("Subscribe", "Related stories", "Sensex ends flat", "All rights reserved"):
        assert junk not in body
    assert e.title not in e.paragraphs  # headline isn't echoed as a paragraph


def test_paragraph_ids_and_offsets_are_stable():
    first = build_paragraphs(extract(FIXTURE, URL).paragraphs)
    second = build_paragraphs(extract(FIXTURE, URL).paragraphs)
    assert first == second
    assert [p.id for p in first] == [f"p{i}" for i in range(len(first))]
    article = "\n\n".join(p.text for p in first)
    for p in first:
        assert article[p.start : p.start + len(p.text)] == p.text


def test_clean_paragraphs_collapses_whitespace_and_drops_fragments():
    raw = ["  short ", "A long enough   paragraph\nwith a line break in the middle."]
    out = clean_paragraphs(raw)
    assert out == ["A long enough paragraph with a line break in the middle."]


def test_features_in_range():
    simple = parse_structure("Prices rose. Shares fell.")
    dense = parse_structure(
        "Banks are unlikely to pass on lower deposit rates quickly, according to economists, "
        "because the liquidity surplus in the banking system has narrowed after the central "
        "bank's foreign exchange intervention to defend the rupee, which drained liquidity."
    )
    assert 0 <= simple < dense <= 1
    assert structure(dense, True) > structure(dense, False)
    assert zipf("the") > zipf("repo rate") > zipf("xqzvt")


def test_url_normalisation_and_hash():
    a = "HTTPS://News.Example:443/rbi?utm_source=x&b=2&a=1#top"
    assert normalize_url(a) == "https://news.example/rbi?a=1&b=2"
    assert url_hash(a) == url_hash("https://news.example/rbi?b=2&a=1")
    assert url_hash(a) != url_hash("https://news.example/rbi?a=2&b=2")
