import pytest

from app import llm
from app.ingest.models import ContentDoc, LLMCall
from app.ingest.safe_fetch import FetchError
from app.ingest.urls import url_hash
from app.store.content_repo import InMemoryContentStore, set_content_store
from scripts.ingest_corpus import (
    CorpusEntry,
    Outcome,
    interleave_sources,
    parse_corpus,
    project_cost,
    run,
    should_attempt,
    stratified_sample,
)


def doc(url: str, cost: float = 0.01) -> ContentDoc:
    call = LLMCall(
        task="extract_demands",
        model="m",
        prompt_version="v1",
        tokens_in=1,
        tokens_out=1,
        cost_usd=cost,
        fell_back=False,
    )
    return ContentDoc(
        content_id=url,
        url=url,
        final_url=url,
        title="t",
        site="s",
        source="fetch",
        fetched_at="now",
        paragraphs=[],
        demands=[],
        demands_dropped=0,
        llm_calls=[call],
    )


@pytest.fixture(autouse=True)
def store():
    s = InMemoryContentStore()
    set_content_store(s)
    yield s
    set_content_store(None)


def test_parse_corpus_skips_comments_blanks_and_duplicates():
    lines = ["# header", "", "https://a/1\tmint", "https://a/1\tmint", "https://w/x\twikipedia"]
    assert parse_corpus(lines) == [
        CorpusEntry("https://a/1", "mint"),
        CorpusEntry("https://w/x", "wikipedia"),
    ]


def test_interleave_and_stratified_sample():
    entries = (
        [CorpusEntry(f"m{i}", "mint") for i in range(5)]
        + [CorpusEntry(f"b{i}", "bbc") for i in range(5)]
        + [CorpusEntry(f"w{i}", "wikipedia") for i in range(5)]
    )
    assert [e.url for e in interleave_sources(entries)[:4]] == ["m0", "b0", "w0", "m1"]
    sample = stratified_sample(entries, 6)
    assert [e.url for e in sample] == ["m0", "b0", "m1", "b1", "w0", "w1"]


def test_should_attempt_skips_done_and_permanent_failures():
    ok = Outcome("u", "s", "ok")
    robots = Outcome("u", "s", "failed", code="robots_disallowed")
    gone = Outcome("u", "s", "failed", code="upstream_error", http_status=404)
    timeout = Outcome("u", "s", "failed", code="timeout")
    llm_down = Outcome("u", "s", "failed", code="LLMUnavailable")
    assert should_attempt(None, False)
    assert not should_attempt(ok, True)
    assert not should_attempt(robots, False) and should_attempt(robots, True)
    assert not should_attempt(gone, False)
    assert should_attempt(timeout, False) and should_attempt(llm_down, False)


def test_project_cost_uses_per_kind_means():
    outcomes = [
        Outcome("a", "mint", "ok", cost_usd=0.01),
        Outcome("b", "bbc", "ok", cost_usd=0.03),
        Outcome("c", "wikipedia", "ok", cost_usd=0.10),
        Outcome("d", "bbc", "failed", code="timeout"),
    ]
    p = project_cost(outcomes, news_total=100, wiki_total=10, build_usd=0.5)
    assert p.news_mean == pytest.approx(0.02)
    assert p.ingest_usd == pytest.approx(2.0 + 1.0)
    assert p.total_usd == pytest.approx(3.5)


async def test_run_records_failures_and_keeps_going():
    async def ingest(url: str) -> ContentDoc:
        if url == "bad":
            raise FetchError("upstream_error", "403", 403)
        if url == "boom":
            raise RuntimeError("unexpected")
        return doc(url)

    recorded: list[Outcome] = []
    entries = [CorpusEntry(u, "mint") for u in ("a", "bad", "boom", "b")]
    outcomes, budget_hit = await run(entries, ingest, recorded.append)
    by_url = {o.url: o for o in recorded}
    assert not budget_hit
    assert by_url["a"].status == "ok" and by_url["a"].new and by_url["a"].cost_usd == 0.01
    assert by_url["bad"].code == "upstream_error" and by_url["bad"].http_status == 403
    assert by_url["boom"].code == "error:RuntimeError"
    assert len(outcomes) == 4


async def test_cached_doc_is_not_marked_new(store):
    store.docs[url_hash("https://x/1")] = doc("https://x/1")

    async def ingest(url: str) -> ContentDoc:
        return store.docs[url_hash(url)]

    outcomes, _ = await run([CorpusEntry("https://x/1", "bbc")], ingest, lambda _: None)
    assert outcomes[0].status == "ok" and not outcomes[0].new


async def test_budget_exceeded_stops_remaining_work():
    calls: list[str] = []

    async def ingest(url: str) -> ContentDoc:
        calls.append(url)
        raise llm.BudgetExceeded("spent")

    entries = [CorpusEntry(str(i), "mint") for i in range(10)]
    outcomes, budget_hit = await run(entries, ingest, lambda _: None, concurrency=1)
    assert budget_hit
    assert calls == ["0"] and outcomes == []
