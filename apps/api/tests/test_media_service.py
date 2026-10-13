"""Open → transcribe → analyse for a YouTube video, with a fake transcribe call and lookup."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app import llm
from app.auth import Caller
from app.config import Settings
from app.content import catalog
from app.ingest import service as ingest
from app.media import service, urls
from app.media.refusals import MediaCapReached, MediaRefused
from app.media.sources import MediaInfo
from app.media.transcript import TranscriptParagraph, TranscriptWindow
from app.store.content_repo import InMemoryContentStore, set_content_store
from app.store.media_repo import get_media_day_repo
from app.store.pending_repo import (
    MAX_ATTEMPTS,
    AnalysisFailed,
    ContentTranscribing,
    get_pending_repo,
)
from app.store.spend_repo import InMemorySpendStore, today_utc
from tests.fakes import FakeLLM
from tests.test_content_api import reply

VIDEO = urls.YouTube("d6fUwCBvVc0")
OTHER = urls.YouTube("xFPILM4UUSg")
CID = urls.content_id(VIDEO)
READER = Caller("reader", False)
DEMO = Caller("demo", True)


def words(n: int, tag: str) -> str:
    return " ".join(f"{tag}{i}" for i in range(n)) + "."


def clock(seconds: int) -> str:
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def settings(**overrides) -> Settings:
    values = dict(
        _env_file=None,
        model_quality="vertex_ai/quality",
        llm_daily_budget_usd=8.0,
        media_daily_budget_usd=3.0,
    )
    return Settings(**(values | overrides))


def info(duration_s: int = 949, language: str | None = "en") -> MediaInfo:
    return MediaInfo("A lecture", "Econ Lectures", duration_s, language=language)


class FakeTranscribe:
    """Answers each call with three 40-word paragraphs at absolute times. A clip with no
    offsets is the whole video, whose length the lookup stub sets in `duration`."""

    def __init__(self, cost: float = 0.02, language: str = "en") -> None:
        self.windows: list[tuple[int, int]] = []
        self.cost = cost
        self.language = language
        self.duration = 949
        self.fail: set[int] = set()
        self.time_out = False

    async def __call__(self, task, schema, clip, *, estimate_usd, meter, check, settings):
        start = 0 if clip.start_s is None else clip.start_s
        end = self.duration if clip.end_s is None else clip.end_s
        self.windows.append((start, end))
        if self.time_out:  # as llm.transcribe: charged its estimate, then MediaTimeout
            meter.cost_usd += estimate_usd
            meter.calls += 1
            raise llm.MediaTimeout("timed out")
        meter.cost_usd += self.cost
        meter.calls += 1
        if start in self.fail:
            raise llm.LLMUnavailable("window failed")
        step = max((end - start) // 3, 1)
        out = TranscriptWindow(
            language=self.language,
            paragraphs=[
                TranscriptParagraph(start=clock(start + i * step), text=words(40, f"w{start}p{i}x"))
                for i in range(3)
            ],
        )
        check(out)
        meta = llm.CallMeta(task, "vertex_ai/quality", "transcribe-v1", 100, 50, self.cost, 0.0,
                            False, 1)  # fmt: skip
        return llm.LLMResult(out, meta)


@pytest.fixture
def env(monkeypatch):
    store = InMemoryContentStore()
    set_content_store(store)
    catalog.reset()
    spend = InMemorySpendStore()
    llm.set_spend_store(spend)
    fake = FakeTranscribe()
    monkeypatch.setattr(llm, "transcribe", fake)
    lookups: list[str] = []
    lookup_result: dict = {"info": info()}

    async def youtube_info(video_id, _settings):
        lookups.append(video_id)
        result = lookup_result["info"]
        if isinstance(result, Exception):
            raise result
        fake.duration = result.duration_s
        return result

    monkeypatch.setattr(service, "youtube_info", youtube_info)
    monkeypatch.setattr(llm, "run_with_meta", FakeLLM(reply))
    yield {
        "store": store,
        "spend": spend,
        "fake": fake,
        "lookups": lookups,
        "lookup": lookup_result,
    }
    set_content_store(None)
    llm.set_spend_store(None)
    catalog.reset()


async def media_count(docs, uid: str) -> int:
    return int((docs.docs.get(f"users/{uid}/media_counts/{today_utc()}") or {}).get("count", 0))


# ---------------------------------------------------------------- the happy path


async def test_open_transcribe_analyse(env, docs):
    s = settings()
    opened = await service.open_media(VIDEO, READER, s)
    assert opened == service.Opened(CID, new=True, stage="transcribe")
    pending = await get_pending_repo().get(CID)
    assert pending.paragraphs == [] and pending.media.video_id == VIDEO.video_id
    assert pending.source == "user_ingested" and "reader" not in repr(pending)
    assert await media_count(docs, "reader") == 1
    assert docs.docs[f"ops/search/days/{today_utc()}"]["media_lookup"] == 1

    await service.transcribe_pending(CID, s)
    assert env["fake"].windows == [(0, 949)]  # one call on the whole video (Round 4)
    pending = await get_pending_repo().get(CID)
    assert pending.stage == "analyse" and pending.windows == {} and pending.lease_token is None
    assert [p.start_s for p in pending.paragraphs] == [0, 316, 632]
    assert pending.media.transcript.windows == 1
    assert pending.media.transcript.cost_usd == pytest.approx(0.02)
    assert pending.transcribe_cost_usd == pytest.approx(0.02)

    doc = await ingest.analyse_pending(CID)
    assert doc.media.kind == "youtube" and doc.media.transcript.prompt_version == "transcribe-v1"
    assert [p.start_s for p in doc.paragraphs] == [0, 316, 632]
    assert doc.llm_calls[0].task == "transcribe"
    assert doc.llm_calls[0].cost_usd == pytest.approx(0.02)


async def test_a_second_open_is_free_while_pending_and_once_ready(env, docs):
    s = settings()
    await service.open_media(VIDEO, READER, s)
    again = await service.open_media(VIDEO, Caller("other", False), s)
    assert again == service.Opened(CID, new=False, stage="transcribe")
    await service.transcribe_pending(CID, s)
    await ingest.analyse_pending(CID)
    ready = await service.open_media(VIDEO, Caller("third", False), s)
    assert ready == service.Opened(CID, new=False, stage=None)
    assert env["lookups"] == [VIDEO.video_id]
    assert await media_count(docs, "other") == 0 and await media_count(docs, "third") == 0
    await service.transcribe_pending(CID, s)  # already done: no model call
    assert len(env["fake"].windows) == 1


async def test_media_off(env):
    with pytest.raises(MediaRefused) as err:
        await service.open_media(VIDEO, READER, settings(media_enabled=False))
    assert err.value.code == "media_off"
    assert env["lookups"] == []


# ---------------------------------------------------------------- refusals, caps, budgets


async def test_a_lookup_refusal_is_remembered_and_the_slot_refunded(env, docs):
    env["lookup"]["info"] = MediaRefused("not_embeddable")
    for _ in range(2):
        with pytest.raises(MediaRefused) as err:
            await service.open_media(VIDEO, READER, settings())
        assert err.value.code == "not_embeddable"
    assert env["lookups"] == [VIDEO.video_id]  # the second answer came from memory
    assert await media_count(docs, "reader") == 0
    assert await get_media_day_repo().refusal(CID, today_utc()) == "not_embeddable"
    assert await get_pending_repo().get(CID) is None


async def test_the_per_reader_cap_refunds_nothing_and_stops_lookups(env):
    s = settings(media_daily_cap=1)
    await service.open_media(VIDEO, READER, s)
    with pytest.raises(MediaCapReached):
        await service.open_media(OTHER, READER, s)
    assert env["lookups"] == [VIDEO.video_id]


async def test_demo_readers_share_one_cap(env):
    s = settings(anon_media_daily_cap=5, anon_global_media_daily_cap=1)
    await service.open_media(VIDEO, DEMO, s)
    with pytest.raises(MediaCapReached):
        await service.open_media(OTHER, Caller("demo2", True), s)


async def test_the_lookup_cap(env, docs):
    docs.docs[f"ops/search/days/{today_utc()}"] = {"calls": 5, "media_lookup": 300}
    with pytest.raises(MediaCapReached):
        await service.open_media(VIDEO, READER, settings())
    assert env["lookups"] == [] and await media_count(docs, "reader") == 0
    assert docs.docs[f"ops/search/days/{today_utc()}"]["calls"] == 5  # search count untouched


async def test_the_media_budget_refuses_at_open(env, docs):
    env["spend"].media = 2.99
    with pytest.raises(llm.BudgetExceeded):
        await service.open_media(VIDEO, READER, settings())
    assert await media_count(docs, "reader") == 0


async def test_a_budget_refusal_before_transcribing_is_free(env):
    s = settings()
    await service.open_media(VIDEO, READER, s)
    env["spend"].media = 2.95
    with pytest.raises(llm.BudgetExceeded):
        await service.transcribe_pending(CID, s)
    pending = await get_pending_repo().get(CID)
    assert pending.transcribe_attempts == 0 and pending.lease_until is None
    assert env["fake"].windows == []


# ---------------------------------------------------------------- transcribe runs


async def test_unknown_language_runs_one_call_and_stops_on_non_english(env):
    s = settings()
    env["lookup"]["info"] = info(language=None)
    env["fake"].language = "hi"
    await service.open_media(VIDEO, READER, s)
    with pytest.raises(MediaRefused) as err:
        await service.transcribe_pending(CID, s)
    assert err.value.code == "not_english"
    assert env["fake"].windows == [(0, 949)]  # one call: the whole video's cost (R4.3 risk)
    pending = await get_pending_repo().get(CID)
    assert pending.refused == "not_english" and pending.transcribe_attempts == 1
    assert pending.transcribe_cost_usd == pytest.approx(0.02)
    assert await get_media_day_repo().refusal(CID, today_utc()) == "not_english"
    with pytest.raises(MediaRefused):  # free from now on
        await service.transcribe_pending(CID, s)
    with pytest.raises(MediaRefused):
        await service.open_media(VIDEO, Caller("other", False), s)
    assert len(env["fake"].windows) == 1


async def test_a_video_near_the_cap_is_one_call_and_a_retry_runs_it_whole(env):
    s = settings()
    env["lookup"]["info"] = info(duration_s=1190)
    await service.open_media(VIDEO, READER, s)
    env["fake"].fail = {0}
    with pytest.raises(llm.LLMUnavailable):
        await service.transcribe_pending(CID, s)
    assert env["fake"].windows == [(0, 1190)]
    pending = await get_pending_repo().get(CID)
    assert pending.windows == {} and pending.transcribe_attempts == 1
    assert pending.transcribe_cost_usd == pytest.approx(0.02)  # the failed call was billed

    env["fake"].fail = set()
    await service.transcribe_pending(CID, s)
    assert env["fake"].windows == [(0, 1190), (0, 1190)]
    pending = await get_pending_repo().get(CID)
    assert pending.stage == "analyse" and pending.media.transcript.cost_usd == pytest.approx(0.04)


async def test_the_ceiling_allows_two_timed_out_runs_and_refuses_the_third(env):
    # 949 s at $0.006 a minute: each timed-out run is charged its $0.095 estimate; the
    # ceiling is 2 × that, so a third run would pass it and is refused before any call.
    s = settings()
    env["fake"].time_out = True
    await service.open_media(VIDEO, READER, s)
    for _ in range(2):
        with pytest.raises(llm.MediaTimeout):
            await service.transcribe_pending(CID, s)
    with pytest.raises(MediaRefused) as err:
        await service.transcribe_pending(CID, s)
    assert err.value.code == "too_costly"
    assert len(env["fake"].windows) == 2
    pending = await get_pending_repo().get(CID)
    assert pending.transcribe_cost_usd == pytest.approx(2 * 949 / 60 * 0.006)


async def test_a_busy_lease_is_202_and_costs_no_attempt(env):
    s = settings()
    await service.open_media(VIDEO, READER, s)
    await get_pending_repo().acquire(CID, datetime.now(UTC), timedelta(minutes=3), "transcribe")
    with pytest.raises(service.TranscribeBusy):
        await service.transcribe_pending(CID, s)
    assert (await get_pending_repo().get(CID)).transcribe_attempts == 0


async def test_attempts_run_out(env):
    s = settings()
    await service.open_media(VIDEO, READER, s)
    env["fake"].fail = {0}
    for _ in range(MAX_ATTEMPTS):
        with pytest.raises(llm.LLMUnavailable):
            await service.transcribe_pending(CID, s)
    with pytest.raises(AnalysisFailed):
        await service.transcribe_pending(CID, s)


async def test_a_cancelled_run_that_billed_counts_an_attempt(env, monkeypatch):
    s = settings()
    await service.open_media(VIDEO, READER, s)

    async def slow(task, schema, clip, *, estimate_usd, meter, check, settings):
        meter.calls += 1
        meter.cost_usd += estimate_usd
        await asyncio.sleep(60)

    monkeypatch.setattr(llm, "transcribe", slow)
    task = asyncio.create_task(service.transcribe_pending(CID, s))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    pending = await get_pending_repo().get(CID)
    assert pending.transcribe_attempts == 1 and pending.lease_until is None
    assert pending.transcribe_cost_usd > 0.02


async def test_analyse_before_the_transcript_is_409_and_no_attempt(env):
    await service.open_media(VIDEO, READER, settings())
    with pytest.raises(ContentTranscribing):
        await ingest.analyse_pending(CID)
    assert (await get_pending_repo().get(CID)).attempts == 0
