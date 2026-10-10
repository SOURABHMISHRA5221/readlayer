"""Held-out list handling for M2.2 (plan §E.2): the domain column, append-only, frozen at 30."""

import pytest

from scripts import eval_heldout
from scripts.ingest_corpus import CorpusEntry, parse_corpus


def test_parse_reads_an_optional_domain_column():
    entries = parse_corpus(
        ["# header", "https://a.test/1\tmint", "https://b.test/2\tbbc\thealth", ""]
    )
    assert entries == [
        CorpusEntry("https://a.test/1", "mint", ""),
        CorpusEntry("https://b.test/2", "bbc", "health"),
    ]


def test_rewriting_keeps_the_first_entries_and_adds_domains(tmp_path, monkeypatch):
    path = tmp_path / "heldout_urls.txt"
    monkeypatch.setattr(eval_heldout, "HELDOUT_FILE", path)
    old = [CorpusEntry(f"https://x.test/{i}", "mint") for i in range(15)]
    path.write_text("# old\n" + "".join(f"{e.url}\t{e.source}\n" for e in old))
    new = [CorpusEntry(f"https://y.test/{i}", "bbc", "science") for i in range(15)]
    eval_heldout.write_heldout(
        [CorpusEntry(e.url, e.source, "finance") for e in eval_heldout.read_heldout()] + new
    )
    again = eval_heldout.read_heldout()
    assert [(e.url, e.source) for e in again[:15]] == [(e.url, e.source) for e in old]
    assert all(e.domain == "finance" for e in again[:15]) and again[15:] == new


async def test_the_business_collector_refuses_once_the_list_has_30(tmp_path, monkeypatch):
    path = tmp_path / "heldout_urls.txt"
    monkeypatch.setattr(eval_heldout, "HELDOUT_FILE", path)
    path.write_text("".join(f"https://x.test/{i}\tmint\tfinance\n" for i in range(30)))
    with pytest.raises(SystemExit, match="frozen"):
        await eval_heldout.collect()


def test_open_spread_adds_up_to_15_non_business_articles():
    from app.graph.taxonomy import BUSINESS_DOMAINS, DOMAIN_IDS

    assert sum(eval_heldout.OPEN_SPREAD.values()) == 15
    assert set(eval_heldout.OPEN_SPREAD) <= set(DOMAIN_IDS) - set(BUSINESS_DOMAINS)
    assert set(eval_heldout.OPEN_SPREAD) == set(eval_heldout.OPEN_SOURCES)
