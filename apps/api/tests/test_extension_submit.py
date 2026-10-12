"""Extension submissions (M8 §A1, §A6): their own id, reuse, defer, onboarding gate."""

import asyncio

import pytest

from app.ingest.urls import ext_id, normalize_url, url_hash
from app.store.docstore import get_doc_store
from app.store.reader_repo import ReaderRepo
from tests import test_two_phase as tp
from tests.fakes import onboard

client = tp.client
store, fetcher, fake_llm = tp.store, tp.fetcher, tp.fake_llm  # fixtures

URL = "https://news.example/live/rbi-policy#latest"
PARAS = [
    "The Reserve Bank of India kept its repo rate unchanged at 6.5% on Wednesday, the tenth "
    "straight meeting without a move, as retail inflation eased to 3.9% in August.",
    "Bond markets had largely priced in the pause, and the yield on the benchmark 10-year "
    "government bond fell 3 basis points to 6.42%, analysts at two brokerages noted today.",
    "The central bank also left the cash reserve ratio, the share of deposits banks must park "
    "with it, unchanged at 4%, and kept its GDP growth forecast for the year at 6.8%.",
]
UPDATED = [*PARAS[:2], PARAS[2] + " Updated at 14:05 IST."]


def submit(c, paragraphs=PARAS, defer=False, url=URL):
    return c.post(
        "/v1/content",
        json={"url": url, "title": "RBI holds", "paragraphs": paragraphs, "defer": defer},
    )


def ingested(uid: str) -> frozenset[str]:
    return asyncio.run(ReaderRepo(get_doc_store()).ingested_ids(uid))


def slots_used(docs, uid: str) -> int:
    return sum(
        d["count"] for p, d in docs.docs.items() if p.startswith(f"users/{uid}/ingest_counts/")
    )


def test_extension_text_gets_its_own_id_and_never_answers_the_fetch_path(store, fetcher, fake_llm):
    body = submit(client("e1", anonymous=True)).json()
    assert body["content_id"] == ext_id(URL, PARAS) != url_hash(URL)
    assert store.docs[body["content_id"]].url == normalize_url(URL)  # no fragment
    pasted = client("e2", anonymous=True).post("/v1/content", json={"url": URL}).json()
    assert pasted["content_id"] == url_hash(URL) and len(fetcher.urls) == 1  # fetched for real
    assert "pii_found_before_backstop" not in pasted


def test_the_fetch_doc_wins_when_present(store, fetcher, fake_llm):
    fetched = client("e1", anonymous=True).post("/v1/content", json={"url": URL}).json()
    calls = len(fake_llm.calls)
    body = submit(client("e2", anonymous=True)).json()
    assert body["content_id"] == fetched["content_id"] and len(fake_llm.calls) == calls
    assert fetched["content_id"] in ingested("e2")


def test_identical_text_is_shared_and_different_text_is_not(store, fetcher, fake_llm):
    a = submit(client("e1", anonymous=True)).json()["content_id"]
    b = submit(client("e2", anonymous=True)).json()["content_id"]
    c = submit(client("e3", anonymous=True), UPDATED).json()["content_id"]
    assert a == b != c
    assert len(fake_llm.calls) == 2


def test_same_reader_changed_text_reuses_their_doc_for_free(store, fetcher, fake_llm, docs):
    me = client("e1", anonymous=True)
    first = submit(me).json()["content_id"]
    again = submit(me, UPDATED).json()
    assert again["content_id"] == first and slots_used(docs, "e1") == 1
    assert len(fake_llm.calls) == 1
    other = submit(client("e2", anonymous=True), UPDATED).json()["content_id"]
    assert other not in (first, url_hash(URL))  # another reader never gets e1's text


def test_defer_stores_pending_only_then_analyse_completes(store, fetcher, fake_llm, docs):
    me = client("e1", anonymous=True)
    body = submit(me, defer=True).json()
    cid = body["content_id"]
    assert body["status"] == "analysing" and [p["id"] for p in body["paragraphs"]] == [
        "p0", "p1", "p2",
    ]  # fmt: skip
    assert fake_llm.calls == [] and f"pending_contents/{cid}" in docs.docs
    assert cid in ingested("e1")
    # Another reader with the same text while it's pending: analysing, recorded, free.
    other = submit(client("e2", anonymous=True), defer=True).json()
    assert other == {**body}
    assert cid in ingested("e2") and slots_used(docs, "e2") == 0
    assert me.post(f"/v1/content/{cid}/analyse").json() == {"content_id": cid, "status": "ready"}
    assert store.docs[cid].source == "extension" and len(fake_llm.calls) == 1


def test_server_redaction_backstop_is_counted_and_applied(store, fetcher, fake_llm):
    leaky = [PARAS[0] + " Write to desk@news.example for tips.", *PARAS[1:]]
    body = submit(client("e1", anonymous=True), leaky).json()
    assert body["pii_found_before_backstop"] == 1
    assert "[REDACTED:email]" in store.docs[body["content_id"]].paragraphs[0].text
    clean = submit(client("e2", anonymous=True), UPDATED).json()
    assert clean["pii_found_before_backstop"] == 0


@pytest.mark.parametrize("finished", [False, True])
def test_unfinished_google_readers_are_sent_to_onboarding(store, fetcher, fake_llm, docs, finished):
    if finished:
        onboard("g1")
    resp = submit(client("g1"))
    if finished:
        assert resp.status_code == 200
        return
    assert resp.status_code == 409 and resp.json()["error"] == "onboarding_required"
    assert store.docs == {} and slots_used(docs, "g1") == 0 and ingested("g1") == frozenset()


def test_demo_readers_are_never_gated(store, fetcher, fake_llm):
    assert submit(client("d1", anonymous=True)).status_code == 200


def test_too_little_text_refunds_the_slot(store, fetcher, fake_llm, docs):
    resp = submit(client("e1", anonymous=True), ["Subscribe to read the full story here."])
    assert resp.status_code == 422 and slots_used(docs, "e1") == 0
