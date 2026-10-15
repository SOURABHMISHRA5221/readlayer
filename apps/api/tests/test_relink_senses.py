"""Decision 66, L2/L3: re-link the demo docs' sense keys and retire their cached cards (fakes)."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.explain.inputs import paragraph_inputs, span_inputs
from app.graph.graph import ConceptGraph
from app.graph.models import ConceptGraphFile
from app.ingest.models import Anchor, ContentDoc, Demand, StoredParagraph
from app.reader.state import ReaderState
from app.store.content_repo import InMemoryContentStore
from app.store.docstore import InMemoryDocStore
from app.store.explain_repo import CACHE, ExplainRepo
from scripts import relink_senses as rs
from tests.test_graph import concept

NOW = datetime(2026, 10, 15, 10, tzinfo=UTC)
GRAPH = ConceptGraph(ConceptGraphFile(version="t+g1", concepts=[
    concept("c_pip_finance", "Pip (finance)", [1, 0, 0], domain="finance"),
    concept("c_pip_benefit", "Personal Independence Payment", [0.9, 0.1, 0], domain="policy"),
    concept("c_omo", "open market operation (OMO)", [0, 1, 0], aliases=["OMO"]),
]))  # fmt: skip


def demand(did, text, target, grown=False):
    return Demand(id=did, paragraph_id="p0", type="concept", label=text, target_id=target,
                  anchor=Anchor(exact=text, prefix="", suffix="", start=0, end=len(text)),
                  salience=0.9, explained_in_text=False, zipf=3.0, grown=grown)  # fmt: skip


def doc(demands, source="fetch", cid="pip"):
    return ContentDoc(content_id=cid, url=f"https://x.test/{cid}", final_url=f"https://x.test/{cid}",
                      title="t", site="x", source=source, fetched_at="now",
                      paragraphs=[StoredParagraph(id="p0", text="Stopping Pip saves little.",
                                                  structure=0.0)],
                      demands=demands, demands_dropped=0, llm_calls=[])  # fmt: skip


PIP = doc([demand("d0", "Pip", "c_pip_finance"), demand("d1", "OMO", "c_omo"),
           demand("d2", "Pip", "c_pip_finance", grown=True),
           demand("d3", "Pip (finance)", "c_pip_finance")])  # fmt: skip


def test_scope_is_bare_sense_keys_only():
    assert [d.id for d in rs.in_scope(PIP, GRAPH, heldout=False)] == ["d0"]
    assert rs.in_scope(PIP, GRAPH, heldout=True) == []
    assert rs.in_scope(doc(PIP.demands, source="user_ingested"), GRAPH, heldout=False) == []


def test_a_link_the_current_rules_would_not_make_is_in_scope():
    """The live PIP case: labelled right, but the concept was grown after the link was made, so
    the bare anchor "Pip" took the finance sense; today the label resolves to the benefit."""
    stale = Demand(id="d9", paragraph_id="p0", type="concept",
                   label="Personal Independence Payment", target_id="c_pip_finance",
                   anchor=Anchor(exact="Pip", prefix="", suffix="", start=0, end=3),
                   salience=0.9, explained_in_text=False, zipf=3.0)  # fmt: skip
    assert [d.id for d in rs.in_scope(doc([stale]), GRAPH, heldout=False)] == ["d9"]


def test_the_estimate_refuses_before_any_call():
    assert rs.estimate(5) <= rs.MAX_USD
    with pytest.raises(SystemExit):
        rs.check_estimate(int(rs.MAX_USD / rs.PER_DOC_USD) + 1)


def entry():
    return rs.Entry("pip", [(d.id, d.target_id) for d in PIP.demands],
                    {"d0": ("c_pip_finance", "c_pip_benefit")})  # fmt: skip


def test_write_changes_only_those_targets_and_revert_restores():
    store = InMemoryContentStore()
    asyncio.run(store.put(PIP))
    assert asyncio.run(rs.apply(store, [entry()], "new", NOW)) == {"pip": "ok"}
    after = store.docs["pip"]
    assert [d.target_id for d in after.demands] == ["c_pip_benefit", "c_omo", "c_pip_finance",
                                                    "c_pip_finance"]  # fmt: skip
    assert after.model_dump(exclude={"demands"}) == PIP.model_dump(exclude={"demands"})
    assert asyncio.run(rs.apply(store, [entry()], "new", NOW)) == {"pip": "changed"}
    assert asyncio.run(rs.apply(store, [entry()], "old", NOW)) == {"pip": "ok"}
    assert store.docs["pip"] == PIP


def test_a_live_growth_claim_refuses_the_write():
    store = InMemoryContentStore()
    asyncio.run(store.put(PIP.model_copy(update={"growing_until": NOW + timedelta(minutes=1)})))
    assert asyncio.run(rs.apply(store, [entry()], "new", NOW)) == {"pip": "growing"}
    assert store.docs["pip"].demands == PIP.demands


def test_retired_hashes_are_the_span_and_paragraph_cards_and_only_those_are_deleted():
    hashes = rs.retired_hashes(PIP, [PIP.demands[0]], GRAPH)
    span = span_inputs(PIP, PIP.demands[0], GRAPH, ReaderState(), NOW, None, "normal")
    para = paragraph_inputs(PIP, "p0", GRAPH, ReaderState(), None, "normal")
    assert hashes == {span.span_hash, para.span_hash}
    docs = InMemoryDocStore()
    repo = ExplainRepo(docs)
    for key, h in (("k1", span.span_hash), ("k2", para.span_hash), ("k3", "other")):
        asyncio.run(repo.put(key, {"span_hash": h, "kind": "verified"}))
    assert sorted(asyncio.run(repo.keys_for_spans(hashes))) == ["k1", "k2"]
    assert asyncio.run(repo.delete_keys(["k1", "k2"])) == 2
    assert [p for p in docs.docs if p.startswith(CACHE)] == [f"{CACHE}/k3"]


def test_only_the_chosen_docs_and_their_cache_hashes_are_applied():
    saved = {"entries": [
        {"content_id": "pip", "before": [], "changes": {}, "span_hashes": ["h1", "h2"]},
        {"content_id": "sebi", "before": [], "changes": {}, "span_hashes": ["h3"]},
    ]}  # fmt: skip
    entries, hashes = rs.chosen(saved, ["pip"])
    assert [e.content_id for e in entries] == ["pip"] and hashes == ["h1", "h2"]
    with pytest.raises(SystemExit):
        rs.chosen(saved, ["missing"])
