"""scripts/ingest_media.py and the reader-free open it uses (Media plan R12, 2.4)."""

import argparse

import pytest

from app.graph.loader import get_graph, set_graph
from app.media import service
from app.media.refusals import MediaRefused
from app.store.content_repo import get_content_store
from app.store.media_repo import get_media_day_repo
from app.store.pending_repo import get_pending_repo
from app.store.spend_repo import today_utc
from scripts import ingest_media
from tests import test_media_service as media
from tests.test_media_service import CID, VIDEO, info, settings
from tests.test_scorer import GRAPH

env = media.env  # the service tests' fixture: fake lookup, transcribe and analysis

URL = VIDEO.canonical
URI = "gs://test/concepts.json"


@pytest.fixture
def graph(monkeypatch):
    """A real run loads the graph as API startup does (load_serving_graph); here, the scorer's."""
    loaded: list[str] = []

    async def load(uri):
        loaded.append(uri)
        set_graph(GRAPH)
        return 0

    previous = get_graph()
    monkeypatch.setattr(ingest_media, "load_serving_graph", load)
    yield loaded
    set_graph(previous)


def reader_docs(docs) -> list[str]:
    return [path for path in docs.docs if path.startswith("users/") or "growth" in path]


async def test_open_with_no_reader_takes_no_reader_or_growth_slot(env, docs):
    opened = await service.open_media(VIDEO, None, settings(growth_enabled=True))
    assert opened == service.Opened(CID, new=True, stage="transcribe")
    pending = await get_pending_repo().get(CID)
    assert pending.source == "user_ingested" and pending.grow_slots == 0
    assert reader_docs(docs) == []
    assert docs.docs[f"ops/search/days/{today_utc()}"]["media_lookup"] == 1  # still counted


async def test_a_refusal_with_no_reader_is_remembered_and_refunds_nothing(env, docs):
    env["lookup"]["info"] = MediaRefused("not_embeddable")
    assert not await ingest_media.ingest(URL, settings())
    assert await get_media_day_repo().refusal(CID, today_utc()) == "not_embeddable"
    assert reader_docs(docs) == []


async def test_look_up_with_no_day_counts_nothing(env, docs):
    got = await service.look_up(VIDEO, settings(), day=None)
    assert got.duration_s == 949
    assert docs.docs == {}


async def test_dry_run_prints_the_plan_with_no_call_and_no_write(env, docs, capsys):
    env["lookup"]["info"] = info(duration_s=486)
    code = await ingest_media.main(argparse.Namespace(urls=[URL], dry_run=True), settings())
    out = capsys.readouterr().out
    assert code == 0
    assert "dry run, no writes" in out and "486 s" in out and "windows: 0-486s" in out
    assert env["fake"].windows == [] and docs.docs == {}
    assert await get_pending_repo().get(CID) is None


async def test_dry_run_refuses_what_the_api_refuses(env, docs, capsys):
    env["lookup"]["info"] = MediaRefused("too_long")
    await ingest_media.main(argparse.Namespace(urls=[URL], dry_run=True), settings())
    assert "refused too_long" in capsys.readouterr().out
    assert docs.docs == {}


async def test_a_real_run_stores_the_transcript_for_every_reader(env, docs, capsys, graph):
    s = settings(concepts_uri=URI)
    code = await ingest_media.main(argparse.Namespace(urls=[URL], dry_run=False), s)
    assert code == 0
    assert graph == [URI]  # the served graph, so demands link (none linked without it)
    doc = await get_content_store().get(CID)
    assert doc.media.kind == "youtube" and doc.source == "user_ingested"
    assert env["fake"].windows == [(0, 949)]
    assert reader_docs(docs) == []
    assert "stored: 120 words" in capsys.readouterr().out
    # Seeded once: a second run (or a reader) opens it free.
    assert await ingest_media.ingest(URL, settings())
    assert len(env["fake"].windows) == 1


async def test_more_than_the_cap_is_refused_before_anything_runs(env, docs):
    urls = [URL] * (ingest_media.MAX_RECORDINGS + 1)
    assert await ingest_media.main(argparse.Namespace(urls=urls, dry_run=True), settings()) == 2
    assert env["lookups"] == []


async def test_a_real_run_refuses_without_a_concept_graph(env, docs, capsys):
    """Analysis with no graph links nothing, so the recording would show no notes, for good."""
    code = await ingest_media.main(argparse.Namespace(urls=[URL], dry_run=False), settings())
    assert code == 2
    assert "CONCEPTS_URI" in capsys.readouterr().out
    assert env["lookups"] == [] and env["fake"].windows == [] and docs.docs == {}


async def test_a_real_run_refuses_when_the_graph_loads_empty(env, docs, capsys, monkeypatch):
    async def empty(uri):
        set_graph(GRAPH.__class__.empty())
        return 0

    monkeypatch.setattr(ingest_media, "load_serving_graph", empty)
    s = settings(concepts_uri=URI)
    assert await ingest_media.main(argparse.Namespace(urls=[URL], dry_run=False), s) == 2
    assert env["lookups"] == [] and docs.docs == {}
