from app.ingest.models import Anchor, ContentDoc, Demand, StoredParagraph
from scripts.build_concepts import Corpus, Merged, collect_candidates


def demand(did: str, label: str, exact: str) -> Demand:
    return Demand(
        id=did,
        paragraph_id="p0",
        anchor=Anchor(exact=exact, prefix="", suffix="", start=0, end=len(exact)),
        type="concept",
        label=label,
        salience=0.9,
        explained_in_text=False,
        zipf=3.0,
    )


def doc(cid: str, demands: list[Demand], text: str = "The repo rate rose.") -> ContentDoc:
    return ContentDoc(
        content_id=cid,
        url=f"https://x/{cid}",
        final_url=f"https://x/{cid}",
        title=cid,
        site="x",
        source="fetch",
        fetched_at="now",
        paragraphs=[StoredParagraph(id="p0", text=text, structure=0.1)],
        demands=demands,
        demands_dropped=0,
        llm_calls=[],
    )


SEEDS = {
    "https://en.wikipedia.org/wiki/Repurchase_agreement": {
        "title": "Repurchase agreement",
        "qid": "Q169357",
    }
}


def corpus(docs, sources, groups) -> Corpus:
    return Corpus(docs, sources, groups, [])


def test_doc_freq_counts_a_duplicate_group_once():
    docs = [
        doc("a", [demand("d0", "Repo rate", "repo rate")]),
        doc("b", [demand("d0", "Repo rate", "repo rate")]),  # syndicated copy of a
        doc("c", [demand("d0", "Yield curve", "yield curve")]),
        doc("d", [demand("d0", "Yield curve", "yield curve")]),
    ]
    sources = {"a": "et", "b": "businessline", "c": "mint", "d": "bbc"}
    groups = {"a": 0, "b": 0, "c": 1, "d": 2}
    cands = collect_candidates(corpus(docs, sources, groups), {})
    # repo rate appears in two docs but one duplicate group -> doc_freq 1
    assert len(cands["repo rate"].groups) == 1
    assert len(cands["yield curve"].groups) == 2


def test_single_doc_candidates_are_collected():
    docs = [doc("a", [demand("d0", "Notional amount", "notional amount")])]
    cands = collect_candidates(corpus(docs, {"a": "et"}, {"a": 0}), {})
    assert set(cands) == {"notional amount"}
    assert len(cands["notional amount"].groups) == 1


def test_seed_kept_even_without_mentions_and_carries_qid():
    cands = collect_candidates(corpus([], {}, {}), SEEDS)
    seed = cands["repurchase agreement"]
    assert seed.seed_qid == "Q169357"
    assert Merged([seed]).label == "Repurchase agreement"


def test_canonical_label_prefers_news_surface_form_and_keeps_wiki_title_alias():
    docs = [
        doc("a", [demand("d0", "Repo rate", "repo rate")]),
        doc("b", [demand("d0", "Repo rate", "repo")]),
        doc("w", [demand("d0", "Repurchase agreement", "repurchase agreement")]),
    ]
    sources = {"a": "et", "b": "mint", "w": "wikipedia"}
    groups = {"a": 0, "b": 1, "w": 2}
    cands = collect_candidates(corpus(docs, sources, groups), SEEDS)
    merged = Merged([cands["repurchase agreement"], cands["repo rate"]])
    assert merged.label == "Repo rate"
    assert "Repurchase agreement" in merged.aliases()
    assert "repo" in merged.aliases()
    assert merged.qid == "Q169357"
    assert merged.is_seed


def test_acronym_surface_form_becomes_label_and_fragments_never_do():
    docs = [
        doc("a", [demand("d0", "Gross domestic product", "GDP")]),
        doc("b", [demand("d0", "Gross domestic product", "GDP")]),
        doc("c", [demand("d0", "Gross domestic product", "gross domestic product")]),
        doc("d", [demand("d0", "Bond yield", "yields")]),
        doc("e", [demand("d0", "Bond yield", "yields")]),
    ]
    sources = dict.fromkeys("abcde", "et")
    groups = {k: i for i, k in enumerate("abcde")}
    cands = collect_candidates(corpus(docs, sources, groups), {})
    gdp = Merged([cands["gross domestic product"]])
    assert gdp.label == "GDP"
    assert "Gross domestic product" in gdp.aliases()
    assert Merged([cands["bond yield"]]).label == "Bond yield"
