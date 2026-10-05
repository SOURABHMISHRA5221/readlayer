from pathlib import Path

from app.content.summary import article_domain
from app.graph.graph import ConceptGraph
from app.graph.models import ConceptGraphFile
from app.ingest import safe_fetch as sf
from app.ingest.extract import Metadata, extract, extract_metadata
from app.ingest.safe_fetch import FetchedPage, FetchError
from app.store.content_repo import InMemoryContentStore
from scripts import backfill_metadata as bf
from tests.test_scorer import GRAPH, demand, doc

FIXTURE = (Path(__file__).parent / "fixtures" / "article_business.html").read_bytes()


def test_extract_keeps_publisher_metadata():
    meta = extract(FIXTURE, "https://news.example/rbi").metadata
    assert meta.author == "Staff Reporter" and meta.published == "2026-10-01"
    assert extract_metadata(FIXTURE, "https://news.example/rbi") == meta


def test_metadata_is_whitespace_collapsed_and_clipped():
    html = f'<html><head><meta name="description" content="  a\n  b {"x" * 900}"></head></html>'
    meta = extract_metadata(html, "https://news.example/x")
    assert meta.description.startswith("a b x") and len(meta.description) == 500


def test_article_domain_weights_salience():
    d = doc(
        [
            demand("a", "c_bond", salience=0.4),
            demand("b", "c_yield_curve", salience=0.4),
            demand("c", "c_inflation", salience=0.7),
            demand("d", None, type_="term", salience=1.0),
        ]
    )
    assert article_domain(d, GRAPH) == "finance"
    assert article_domain(doc([]), GRAPH) is None
    assert article_domain(d, ConceptGraph(ConceptGraphFile(version="e", concepts=[]))) is None


class FakeFetcher:
    def __init__(self, error=None):
        self.error, self.urls = error, []

    async def fetch(self, url, **_):
        self.urls.append(url)
        if self.error:
            raise self.error
        return FetchedPage(url, FIXTURE, "utf-8")


async def test_backfill_updates_only_metadata_and_skips_filled():
    store = InMemoryContentStore()
    bare = doc([demand("a", "c_bond")])
    filled = bare.model_copy(update={"content_id": "y", "author": "Someone"})
    store.docs = {"x": bare, "y": filled}
    fetcher = FakeFetcher()
    sf.set_fetcher(fetcher)
    try:
        first = await bf.backfill_one(bare, store, dry_run=False, force=False)
        second = await bf.backfill_one(filled, store, dry_run=False, force=False)
    finally:
        sf.set_fetcher(None)
    assert (first.status, second.status) == ("updated", "skipped")
    updated = store.docs["x"]
    assert updated.author == "Staff Reporter" and updated.published == "2026-10-01"
    assert updated.model_copy(update={"author": None, "published": None}) == bare
    assert fetcher.urls == ["u"]


async def test_backfill_dry_run_and_failures_write_nothing():
    store = InMemoryContentStore()
    bare = doc([])
    store.docs = {"x": bare}
    sf.set_fetcher(FakeFetcher())
    try:
        assert (await bf.backfill_one(bare, store, dry_run=True, force=False)).status == "updated"
    finally:
        sf.set_fetcher(None)
    sf.set_fetcher(FakeFetcher(FetchError("robots_disallowed", "no")))
    try:
        result = await bf.backfill_one(bare, store, dry_run=False, force=False)
    finally:
        sf.set_fetcher(None)
    assert (result.status, result.code) == ("failed", "robots_disallowed")
    assert store.docs["x"] == bare
    assert bf.with_metadata(bare, Metadata()) == bare


def test_image_url_must_be_absolute_http():
    def image(content):
        html = f'<html><head><meta property="og:image" content="{content}"></head></html>'
        return extract_metadata(html, "https://news.example/x").image

    assert image("https://cdn.news.example/a.jpg") == "https://cdn.news.example/a.jpg"
    assert image("javascript:alert(1)") is None
    assert image("data:image/png;base64,AAAA") is None
    assert image("https://x/" + "a" * 1200) is None
