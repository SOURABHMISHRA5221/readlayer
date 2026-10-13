import asyncio
from types import SimpleNamespace

import litellm
import pytest

from app import llm
from app.config import Settings
from app.llm import AudioClip, MediaMeter, YouTubeClip
from app.media.transcript import TranscriptWindow, Window, check_window
from app.store.spend_repo import InMemorySpendStore

QUALITY = "vertex_ai/gemini-3.8-flash"  # in LiteLLM's price map: $0.75 / $3.75 per 1M, no audio
TEXT_PRICE = 0.75e-6
AUDIO_PRICE = 2.5e-6
VALID = '{"language": "en", "paragraphs": [{"start": "00:01", "text": "Hello there."}]}'
CLIP = YouTubeClip("https://www.youtube.com/watch?v=d6fUwCBvVc0")  # the whole video


def media_settings(**overrides) -> Settings:
    values = dict(
        _env_file=None,
        gcp_project="test-project",
        model_fast="vertex_ai/fast",
        model_quality=QUALITY,
        model_fallback="vertex_ai/fallback",
        llm_daily_budget_usd=8.0,
        media_daily_budget_usd=3.0,
        model_audio_price_overrides={QUALITY: AUDIO_PRICE},
    )
    return Settings(**(values | overrides))


def response(content, *, tokens_in=19_284, tokens_out=2_722, audio=15_000, finish="stop"):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content), finish_reason=finish)],
        usage=SimpleNamespace(
            prompt_tokens=tokens_in,
            completion_tokens=tokens_out,
            prompt_tokens_details=SimpleNamespace(audio_tokens=audio),
        ),
    )


class FakeLiteLLM:
    def __init__(self, monkeypatch, script: list) -> None:
        self.script = list(script)
        self.calls: list[dict] = []
        monkeypatch.setattr(litellm, "acompletion", self.acompletion)
        monkeypatch.setattr(litellm, "supports_response_schema", lambda model: True)

        def no_completion_cost(**_):
            raise AssertionError("media calls are priced from token counts, not completion_cost")

        monkeypatch.setattr(litellm, "completion_cost", no_completion_cost)

    async def acompletion(self, **kwargs):
        self.calls.append(kwargs)
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        if callable(item):
            return await item()
        return item


@pytest.fixture
def store(monkeypatch):
    from tenacity import wait_none

    store = InMemorySpendStore()
    monkeypatch.setattr(llm, "retry_wait", wait_none())
    llm.set_spend_store(store)
    yield store
    llm.set_spend_store(None)


async def run(clip=CLIP, settings=None, meter=None, check=None, estimate=0.05):
    return await llm.transcribe(
        "transcribe",
        TranscriptWindow,
        clip,
        estimate_usd=estimate,
        meter=meter if meter is not None else MediaMeter(),
        check=check,
        settings=settings or media_settings(),
    )


# ---------------------------------------------------------------- request shape


async def test_youtube_request_uses_the_measured_settings(monkeypatch, store):
    fake = FakeLiteLLM(monkeypatch, [response(VALID)])
    result = await run()
    call = fake.calls[0]
    assert call["model"] == QUALITY
    assert call["reasoning_effort"] == "low"
    assert call["max_tokens"] == 16_000
    assert call["timeout"] == 90.0
    assert call["num_retries"] == 0
    assert call["response_format"] is TranscriptWindow
    system, user = call["messages"]
    assert "untrusted data" in system["content"] and "<<<CONTENT>>>" not in system["content"]
    text, part = user["content"]
    assert text["text"].startswith("Transcribe every spoken word")
    assert part == {
        "type": "file",
        "file": {
            "file_id": CLIP.url,
            "format": "video/mp4",
            "detail": "low",
            "video_metadata": {"fps": 0.1},  # no offsets: offset windows can hang (Round 4)
        },
    }
    assert result.meta.prompt_version == "transcribe-v1"
    assert result.output.paragraphs[0].text == "Hello there."


async def test_an_offset_clip_still_sends_its_offsets(monkeypatch, store):
    fake = FakeLiteLLM(monkeypatch, [response(VALID)])
    await run(clip=YouTubeClip(CLIP.url, 600, 949))
    metadata = fake.calls[0]["messages"][1]["content"][1]["file"]["video_metadata"]
    assert metadata == {"fps": 0.1, "start_offset": "600s", "end_offset": "949s"}


async def test_audio_is_sent_inline_as_base64(monkeypatch, store):
    fake = FakeLiteLLM(monkeypatch, [response(VALID)])
    await run(clip=AudioClip(memoryview(b"\xff\xfbabc")))
    part = fake.calls[0]["messages"][1]["content"][1]
    assert part == {
        "type": "file",
        "file": {"file_data": "data:audio/mpeg;base64,//thYmM=", "format": "audio/mpeg"},
    }


# ---------------------------------------------------------------- cost


async def test_cost_pins_measured_row_11_at_the_text_price(monkeypatch, store):
    # Row 11 (50:00–60:00, quality, low): 19,284 in / 2,722 out, ledger $0.0247 with audio
    # priced like text.
    FakeLiteLLM(monkeypatch, [response(VALID)])
    settings = media_settings(model_audio_price_overrides={QUALITY: TEXT_PRICE})
    result = await run(settings=settings)
    assert result.meta.cost_usd == pytest.approx(0.0246705)
    assert round(store.total, 4) == 0.0247


async def test_audio_tokens_use_the_audio_price(monkeypatch, store):
    FakeLiteLLM(monkeypatch, [response(VALID)])
    meter = MediaMeter()
    result = await run(meter=meter)
    expected = 4_284 * TEXT_PRICE + 15_000 * AUDIO_PRICE + 2_722 * 3.75e-6  # ≈ $0.0509
    assert result.meta.cost_usd == pytest.approx(expected)
    assert store.total == pytest.approx(expected)
    assert store.media == pytest.approx(expected)  # counted in media's own share too
    assert meter.cost_usd == pytest.approx(expected) and meter.calls == 1


async def test_a_model_with_no_audio_price_is_refused_before_any_call(monkeypatch, store):
    fake = FakeLiteLLM(monkeypatch, [response(VALID)])
    with pytest.raises(llm.LLMRejected, match="no audio price"):
        await run(settings=media_settings(model_audio_price_overrides={}))
    assert fake.calls == [] and store.calls == 0


async def test_litellm_audio_price_wins_over_the_override(monkeypatch, store):
    FakeLiteLLM(monkeypatch, [response(VALID, tokens_in=1_000, tokens_out=0, audio=1_000)])
    entry = dict(litellm.model_cost[QUALITY], input_cost_per_audio_token=1e-6)
    monkeypatch.setitem(litellm.model_cost, QUALITY, entry)
    result = await run()
    assert result.meta.cost_usd == pytest.approx(1_000 * 1e-6)


# ---------------------------------------------------------------- budgets


async def test_the_daily_budget_refuses_before_calling(monkeypatch):
    fake = FakeLiteLLM(monkeypatch, [response(VALID)])
    llm.set_spend_store(InMemorySpendStore(initial_usd=8.0))
    try:
        with pytest.raises(llm.BudgetExceeded):
            await run()
    finally:
        llm.set_spend_store(None)
    assert fake.calls == []


async def test_the_media_budget_refuses_before_calling(monkeypatch):
    fake = FakeLiteLLM(monkeypatch, [response(VALID)])
    llm.set_spend_store(InMemorySpendStore(initial_usd=3.0, media_usd=3.0))
    try:
        with pytest.raises(llm.BudgetExceeded, match="media"):
            await run()
    finally:
        llm.set_spend_store(None)
    assert fake.calls == []


async def test_check_media_budget_counts_what_is_needed(store):
    store.total, store.media = 1.0, 2.9
    await llm.check_media_budget(0.05, settings=media_settings())
    with pytest.raises(llm.BudgetExceeded):
        await llm.check_media_budget(0.2, settings=media_settings())


# ---------------------------------------------------------------- errors and retries


def rate_limit():
    return litellm.RateLimitError("slow down", llm_provider="vertex_ai", model="x")


def timeout():
    return litellm.Timeout("timed out", model="x", llm_provider="vertex_ai")


def bad_request():
    return litellm.BadRequestError("400 invalid argument", model="x", llm_provider="vertex_ai")


def not_found():
    return litellm.NotFoundError("no such model", llm_provider="vertex_ai", model="x")


async def test_transient_errors_are_retried_on_the_same_model(monkeypatch, store):
    fake = FakeLiteLLM(monkeypatch, [rate_limit(), response(VALID)])
    result = await run()
    assert [c["model"] for c in fake.calls] == [QUALITY, QUALITY]
    assert result.meta.attempts == 2


async def test_a_timeout_is_charged_once_and_not_retried(monkeypatch, store):
    fake = FakeLiteLLM(monkeypatch, [timeout(), response(VALID)])
    meter = MediaMeter()
    with pytest.raises(llm.MediaTimeout):
        await run(meter=meter, estimate=0.05)
    assert len(fake.calls) == 1 and meter.calls == 1
    assert meter.cost_usd == pytest.approx(0.05) and store.media == pytest.approx(0.05)
    assert store.calls == 1


def test_a_media_timeout_is_a_timeout_error():
    """So the route's existing TimeoutError handler answers 504, not 503 (R4.2)."""
    assert issubclass(llm.MediaTimeout, TimeoutError)
    assert not issubclass(llm.MediaTimeout, llm.LLMError)


async def test_a_cancelled_call_is_charged_its_estimate(monkeypatch, store):
    started = asyncio.Event()

    async def hang():
        started.set()
        await asyncio.sleep(60)

    FakeLiteLLM(monkeypatch, [hang])
    meter = MediaMeter()
    task = asyncio.create_task(run(meter=meter, estimate=0.05))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert meter.cost_usd == pytest.approx(0.05) and store.media == pytest.approx(0.05)


async def test_retries_run_out_as_unavailable_and_never_fall_back(monkeypatch, store):
    fake = FakeLiteLLM(monkeypatch, [rate_limit()] * 3)
    with pytest.raises(llm.LLMUnavailable):
        await run()
    assert {c["model"] for c in fake.calls} == {QUALITY}


async def test_a_bad_request_is_rejected_without_retry(monkeypatch, store):
    fake = FakeLiteLLM(monkeypatch, [bad_request()])
    with pytest.raises(llm.LLMRejected):
        await run()
    assert len(fake.calls) == 1


async def test_model_not_found_is_unavailable_with_no_fallback(monkeypatch, store):
    fake = FakeLiteLLM(monkeypatch, [not_found()])
    with pytest.raises(llm.LLMUnavailable):
        await run()
    assert len(fake.calls) == 1


# ---------------------------------------------------------------- invalid output


async def test_cut_off_output_is_asked_again_once(monkeypatch, store):
    fake = FakeLiteLLM(monkeypatch, [response(VALID, finish="length"), response(VALID)])
    result = await run()
    assert len(fake.calls) == 2
    assert fake.calls[0]["messages"] == fake.calls[1]["messages"]  # repair-free: same request
    assert result.meta.attempts == 2
    assert store.calls == 2  # both billed


async def test_a_failed_check_is_asked_again_then_rejected(monkeypatch, store):
    looping = (
        '{"language": "en", "paragraphs": ['
        + ",".join(
            '{"start": "00:01", "text": "the same long sentence over and over"}' for _ in range(3)
        )
        + "]}"
    )
    fake = FakeLiteLLM(monkeypatch, [response(looping), response(looping)])
    meter = MediaMeter()
    window = Window(0, 0, 600)
    with pytest.raises(llm.LLMRejected, match="invalid output twice"):
        await run(meter=meter, check=lambda o: check_window(o, window, relative_only=False))
    assert len(fake.calls) == 2 and meter.calls == 2


async def test_schema_invalid_output_is_asked_again(monkeypatch, store):
    bad = '{"language": "en", "paragraphs": [{"start": "1549", "text": "x"}]}'
    FakeLiteLLM(monkeypatch, [response(bad), response(VALID)])
    result = await run()
    assert result.output.paragraphs[0].start == "00:01"
