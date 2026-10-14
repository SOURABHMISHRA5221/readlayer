"""Open → transcribe → analyse for an Apple podcast episode, and the switches (Media plan Round 5:
5.1, 5.2, 5.4, 5R3, 5R5, 5R6, 5R7). Fake lookup, probe, fetcher and transcribe call; the MP3 is
synthetic (32 kbps MPEG 1 at 48 kHz: 96-byte frames of 24 ms, 4,000 bytes a second)."""

import pytest

from app import llm
from app.config import Settings
from app.content import catalog
from app.ingest import service as ingest
from app.ingest.safe_fetch import FetchedAudio, FetchError, set_fetcher
from app.media import service, urls
from app.media.refusals import MediaRefused, MediaUnavailable
from app.media.sources import AudioProbe, MediaInfo
from app.media.transcript import TranscriptParagraph, TranscriptWindow
from app.store.content_repo import InMemoryContentStore, set_content_store
from app.store.media_repo import get_media_day_repo, media_day_path
from app.store.pending_repo import get_pending_repo
from app.store.spend_repo import InMemorySpendStore, today_utc
from tests.fakes import FakeLLM
from tests.test_content_api import reply
from tests.test_media_service import LONG_CAPS, READER, clock, settings, words
from tests.test_mp3 import stream

EPISODE = urls.ApplePodcast("1200361736", "1000650000001")
CID = urls.content_id(EPISODE)
AUDIO_URL = "https://cdn.example/show/episode.mp3"
BYTES_PER_S = 4000


def episode_info(duration_s: int = 1290) -> MediaInfo:
    return MediaInfo("An episode", "A show", duration_s, audio_url=AUDIO_URL)


class FakeFetcher:
    """fetch_audio returns `data` (a fresh bytearray each time) or raises `error`."""

    def __init__(self, seconds: float) -> None:
        self.data = stream(seconds)
        self.error: FetchError | None = None
        self.fetches = 0

    async def fetch_audio(self, url, *, max_bytes, expected_bytes=None):
        assert url == AUDIO_URL
        self.fetches += 1
        if self.error is not None:
            raise self.error
        return FetchedAudio(url, bytearray(self.data))


class FakeAudioTranscribe:
    """Three 40-word paragraphs per piece at times relative to the piece, as audio comes back.
    Records each call's piece length in seconds and which calls overlapped."""

    def __init__(self, cost: float = 0.01) -> None:
        self.calls: list[int] = []
        self.cost = cost
        self.language = "en"
        self.fail: set[int] = set()  # call numbers (0-based) that fail after billing
        self.inflight = 0
        self.overlapped: list[int] = []

    async def __call__(self, task, schema, clip, *, estimate_usd, meter, check, settings):
        assert isinstance(clip, llm.AudioClip)
        n = len(self.calls)
        length = round(len(clip.data) / BYTES_PER_S)
        self.calls.append(length)
        if self.inflight:
            self.overlapped.append(n)
        self.inflight += 1
        try:
            meter.cost_usd += self.cost
            meter.calls += 1
            if n in self.fail:
                raise llm.LLMUnavailable("window failed")
            step = length // 3
            out = TranscriptWindow(
                language=self.language,
                paragraphs=[
                    TranscriptParagraph(start=clock(i * step), text=words(40, f"c{n}p{i}x"))
                    for i in range(3)
                ],
            )
            check(out)
            meta = llm.CallMeta(task, "vertex_ai/quality", "transcribe-v1", 100, 50, self.cost,
                                0.0, False, 1)  # fmt: skip
            return llm.LLMResult(out, meta)
        finally:
            self.inflight -= 1


@pytest.fixture
def env(monkeypatch):
    store = InMemoryContentStore()
    set_content_store(store)
    catalog.reset()
    spend = InMemorySpendStore()
    llm.set_spend_store(spend)
    fake = FakeAudioTranscribe()
    monkeypatch.setattr(llm, "transcribe", fake)
    fetcher = FakeFetcher(1300)
    set_fetcher(fetcher)  # type: ignore[arg-type]
    calls: list[str] = []
    lookup: dict = {"info": episode_info(), "probe": AudioProbe(AUDIO_URL, 5_200_000, 32)}

    async def apple_episode(show_id, episode_id, _settings):
        calls.append("apple")
        if isinstance(lookup["info"], Exception):
            raise lookup["info"]
        return lookup["info"]

    async def probe_audio(url, _settings, _fetcher):
        calls.append("probe")
        if isinstance(lookup["probe"], Exception):
            raise lookup["probe"]
        return lookup["probe"]

    monkeypatch.setattr(service, "apple_episode", apple_episode)
    monkeypatch.setattr(service, "probe_audio", probe_audio)
    monkeypatch.setattr(llm, "run_with_meta", FakeLLM(reply))
    yield {
        "store": store,
        "spend": spend,
        "fake": fake,
        "fetcher": fetcher,
        "calls": calls,
        "lookup": lookup,
    }
    set_fetcher(None)
    set_content_store(None)
    llm.set_spend_store(None)
    catalog.reset()
    assert not service._AUDIO_SLOT.locked()  # every exit released it (5R6)


async def remembered(content_id: str) -> str | None:
    return await get_media_day_repo().refusal(content_id, today_utc())


# ---------------------------------------------------------------- the happy path


async def test_open_transcribe_analyse(env, docs):
    s = settings()
    opened = await service.open_media(EPISODE, READER, s)
    assert opened == service.Opened(CID, new=True, stage="transcribe")
    assert env["calls"] == ["apple", "probe"]
    assert docs.docs[f"ops/search/days/{today_utc()}"]["media_lookup"] == 2
    pending = await get_pending_repo().get(CID)
    assert pending.url == EPISODE.canonical and pending.title == "An episode"
    assert pending.media.kind == "audio" and pending.media.audio_url == AUDIO_URL
    assert pending.media.language is None and pending.media.duration_s == 1290

    await service.transcribe_pending(CID, s)
    fake = env["fake"]
    assert fake.calls == [600, 600, 100]  # time-only pieces: 0–600, 600–1200, 1200–1300
    assert 0 not in fake.overlapped  # window 1 ran alone (R8)
    pending = await get_pending_repo().get(CID)
    assert pending.stage == "analyse" and pending.windows == {}
    assert pending.audio_fingerprint is None
    assert pending.media.duration_s == 1300  # the walk's length, not the lookup's (5R3)
    starts = [p.start_s for p in pending.paragraphs]
    assert starts == [0, 200, 400, 600, 800, 1000, 1200, 1233, 1266]  # relative → absolute
    assert pending.media.transcript.windows == 3
    assert pending.transcribe_cost_usd == pytest.approx(0.03)

    doc = await ingest.analyse_pending(CID)
    assert doc.media.kind == "audio" and doc.media.audio_url == AUDIO_URL
    assert [p.start_s for p in doc.paragraphs] == starts


async def test_apple_without_a_length_is_estimated_from_the_bitrate(env):
    env["lookup"]["info"] = episode_info(duration_s=0)
    env["lookup"]["probe"] = AudioProbe(AUDIO_URL, 5_200_000, 32)  # 1,300 s at 32 kbps
    await service.open_media(EPISODE, READER, settings())
    assert (await get_pending_repo().get(CID)).media.duration_s == 1300


async def test_an_estimate_over_the_cap_is_too_long_and_remembered(env):
    env["lookup"]["info"] = episode_info(duration_s=0)
    env["lookup"]["probe"] = AudioProbe(AUDIO_URL, 12_000_000, 32)  # 3,000 s
    with pytest.raises(MediaRefused) as err:
        await service.open_media(EPISODE, READER, settings())
    assert err.value.code == "too_long" and await remembered(CID) == "too_long"


# ---------------------------------------------------------------- refusals before any I/O


@pytest.mark.parametrize(
    ("media", "code"),
    [
        (urls.AudioFile("https://cdn.example/ep.mp3"), "apple_link_only"),
        (urls.ApplePodcast("1200361736", None), "not_an_episode"),
    ],
)
async def test_links_answered_before_any_lookup(env, docs, media, code):
    with pytest.raises(MediaRefused) as err:
        await service.open_media(media, READER, settings())
    assert err.value.code == code
    assert env["calls"] == [] and f"ops/search/days/{today_utc()}" not in docs.docs
    assert await remembered(urls.content_id(media)) is None


@pytest.mark.parametrize("switch", ["media_enabled", "media_audio_enabled"])
async def test_a_switched_off_podcast_is_never_remembered_and_costs_nothing(env, docs, switch):
    with pytest.raises(MediaRefused) as err:
        await service.open_media(EPISODE, READER, settings(**{switch: False}))
    assert err.value.code == "media_off" and env["calls"] == []
    assert await remembered(CID) is None
    await service.open_media(EPISODE, READER, settings())  # back on: opens at once

    with pytest.raises(MediaRefused) as err:
        await service.transcribe_pending(CID, settings(**{switch: False}))
    assert err.value.code == "media_off"
    pending = await get_pending_repo().get(CID)
    assert pending.refused is None and pending.transcribe_attempts == 0
    assert pending.lease_until is None and env["fetcher"].fetches == 0
    assert await remembered(CID) is None
    await service.transcribe_pending(CID, settings())
    assert (await get_pending_repo().get(CID)).stage == "analyse"


async def test_the_video_switch_leaves_podcasts_alone(env):
    s = settings(media_video_enabled=False)
    await service.open_media(EPISODE, READER, s)
    await service.transcribe_pending(CID, s)
    with pytest.raises(MediaRefused) as err:
        await service.open_media(urls.YouTube("d6fUwCBvVc0"), READER, s)
    assert err.value.code == "media_off"


async def test_remember_refusal_skips_switch_answers(docs):
    repo = get_media_day_repo()
    await repo.remember_refusal(CID, "media_off", today_utc())
    await repo.remember_refusal(CID, "apple_link_only", today_utc())
    assert media_day_path(today_utc()) not in docs.docs
    await repo.remember_refusal(CID, "too_long", today_utc())
    assert await repo.refusal(CID, today_utc()) == "too_long"


# ---------------------------------------------------------------- transient vs permanent (5R5)


async def test_a_transient_probe_failure_refunds_and_is_not_remembered(env, docs):
    env["lookup"]["probe"] = MediaUnavailable("audio")
    with pytest.raises(MediaUnavailable):
        await service.open_media(EPISODE, READER, settings())
    assert await remembered(CID) is None and await get_pending_repo().get(CID) is None
    count = docs.docs.get(f"users/reader/media_counts/{today_utc()}") or {}
    assert int(count.get("count", 0)) == 0


async def test_a_transient_fetch_failure_uses_no_attempt(env):
    s = settings()
    await service.open_media(EPISODE, READER, s)
    env["fetcher"].error = FetchError("timeout", "timed out")
    with pytest.raises(MediaUnavailable):
        await service.transcribe_pending(CID, s)
    pending = await get_pending_repo().get(CID)
    assert pending.transcribe_attempts == 0 and pending.refused is None
    assert pending.lease_until is None and await remembered(CID) is None
    env["fetcher"].error = None
    await service.transcribe_pending(CID, s)  # the next try runs
    assert (await get_pending_repo().get(CID)).stage == "analyse"


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (FetchError("upstream_error", "gone", status=404), "unsupported_audio"),
        (FetchError("robots_disallowed", "robots"), "unsupported_audio"),
        (FetchError("too_large", "big"), "too_long"),
    ],
)
async def test_a_permanent_fetch_failure_is_refused_and_remembered(env, error, code):
    s = settings()
    await service.open_media(EPISODE, READER, s)
    env["fetcher"].error = error
    with pytest.raises(MediaRefused) as err:
        await service.transcribe_pending(CID, s)
    assert err.value.code == code
    pending = await get_pending_repo().get(CID)
    assert pending.refused == code and pending.transcribe_attempts == 0  # nothing billed
    assert await remembered(CID) == code and env["fake"].calls == []


async def test_the_ceiling_follows_the_walks_length_not_the_lookups(env):
    # Apple said 60 s: a ceiling from that ($0.012) would refuse the first $0.06 window.
    s = settings()
    env["lookup"]["info"] = episode_info(duration_s=60)
    await service.open_media(EPISODE, READER, s)
    await service.transcribe_pending(CID, s)
    assert env["fake"].calls == [600, 600, 100]


async def test_the_walks_length_over_the_cap_is_refused_before_any_call(env):
    s = settings(media_max_audio_s=1295)
    env["lookup"]["info"] = episode_info(duration_s=1290)
    await service.open_media(EPISODE, READER, s)
    with pytest.raises(MediaRefused) as err:
        await service.transcribe_pending(CID, s)
    assert err.value.code == "too_long" and env["fake"].calls == []


async def test_stitched_in_ads_past_apples_length_still_transcribe(env):
    """Under the default caps: an Indicator episode listed at 565 s downloaded at 652 s (ads
    Apple's length leaves out). It transcribes; the 52 s tail joins window 1."""
    defaults = {name: Settings.model_fields[name].default for name in LONG_CAPS}
    assert defaults["media_max_audio_s"] == 720
    s = settings(**defaults)
    env["lookup"]["info"] = episode_info(duration_s=565)
    env["fetcher"].data = stream(652)
    await service.open_media(EPISODE, READER, s)
    await service.transcribe_pending(CID, s)
    assert env["fake"].calls == [652]
    assert (await get_pending_repo().get(CID)).stage == "analyse"


# ---------------------------------------------------------------- language, slot, fingerprint


async def test_non_english_stops_after_window_one(env):
    s = settings()
    env["fake"].language = "hi"
    await service.open_media(EPISODE, READER, s)
    with pytest.raises(MediaRefused) as err:
        await service.transcribe_pending(CID, s)
    assert err.value.code == "not_english" and env["fake"].calls == [600]
    pending = await get_pending_repo().get(CID)
    assert pending.refused == "not_english" and pending.transcribe_attempts == 1
    assert await remembered(CID) == "not_english"


async def test_a_busy_audio_slot_leaves_the_lease_and_counters_alone(env):
    s = settings()
    await service.open_media(EPISODE, READER, s)
    await service._AUDIO_SLOT.acquire()  # another podcast on this instance
    try:
        with pytest.raises(service.TranscribeBusy):
            await service.transcribe_pending(CID, s)
    finally:
        service._AUDIO_SLOT.release()
    pending = await get_pending_repo().get(CID)
    assert pending.lease_until is None and pending.lease_token is None
    assert pending.transcribe_attempts == 0 and pending.attempts == 0
    assert env["fetcher"].fetches == 0


async def test_the_slot_is_free_after_a_budget_refusal_and_after_a_refused_run(env):
    s = settings()
    await service.open_media(EPISODE, READER, s)
    env["spend"].media = 2.95
    with pytest.raises(llm.BudgetExceeded):
        await service.transcribe_pending(CID, s)
    assert not service._AUDIO_SLOT.locked()
    env["spend"].media = 0.0
    env["fetcher"].error = FetchError("upstream_error", "gone", status=410)
    with pytest.raises(MediaRefused):
        await service.transcribe_pending(CID, s)
    assert not service._AUDIO_SLOT.locked()


async def test_a_retry_on_the_same_bytes_keeps_saved_windows(env):
    s = settings(media_audio_parallel_windows=1)
    await service.open_media(EPISODE, READER, s)
    env["fake"].fail = {2}  # window 3 fails after windows 1 and 2 are saved
    with pytest.raises(llm.LLMUnavailable):
        await service.transcribe_pending(CID, s)
    pending = await get_pending_repo().get(CID)
    assert set(pending.windows) == {"0", "1"} and pending.audio_fingerprint == "54167:5200032"
    env["fake"].fail = set()
    await service.transcribe_pending(CID, s)
    assert env["fake"].calls == [600, 600, 100, 100]  # only window 3 again


async def test_different_bytes_on_a_retry_drop_the_saved_windows(env):
    s = settings(media_audio_parallel_windows=1)
    await service.open_media(EPISODE, READER, s)
    env["fake"].fail = {2}
    with pytest.raises(llm.LLMUnavailable):
        await service.transcribe_pending(CID, s)
    env["fake"].fail = set()
    env["fetcher"].data = stream(1320)  # another ad stitched in (dynamic ads)
    await service.transcribe_pending(CID, s)
    assert env["fake"].calls == [600, 600, 100, 600, 600, 120]  # starts over
    pending = await get_pending_repo().get(CID)
    assert pending.media.duration_s == 1320
    assert pending.transcribe_cost_usd == pytest.approx(0.06)  # the dropped windows still count
