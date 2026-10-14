"""One transcribe call on a YouTube video, through llm.transcribe, ledger in the emulator.

    uv run python -m scripts.probe_media <video_id> <duration_s>
        [--start S --end S] [--effort low|default] [--timeout SECONDS]

No --start/--end = the whole video (no offsets). One attempt, no retry.
"""

import argparse
import asyncio
import dataclasses
import os
import time

os.environ["FIRESTORE_EMULATOR_HOST"] = "127.0.0.1:8085"
os.environ["FIRESTORE_PROJECT"] = "demo-readlayer"
os.environ["ENV"] = "dev"
os.environ["MODEL_AUDIO_PRICE_OVERRIDES"] = '{"vertex_ai/gemini-3.8-flash": 2.5e-6}'
os.environ.setdefault("LLM_DAILY_BUDGET_USD", "1.0")  # set it to the seed's HARNESS_BUDGET_USD
os.environ["LLM_MAX_RETRIES"] = "0"  # one attempt: a probe must not double its cost

from app import llm  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.media import urls  # noqa: E402
from app.media.transcript import TranscriptWindow, Window, check_window  # noqa: E402


async def main(a: argparse.Namespace) -> None:
    settings = get_settings()
    assert settings.db_project == "demo-readlayer", settings.db_project
    effort = None if a.effort == "default" else a.effort
    llm.ROUTES["transcribe"] = dataclasses.replace(
        llm.ROUTES["transcribe"], reasoning_effort=effort, timeout_s=a.timeout
    )
    start = a.start or 0
    end = a.end or a.duration
    window = Window(0, start, end)
    clip = llm.YouTubeClip(urls.YouTube(a.video_id).canonical, a.start, a.end)
    meter = llm.MediaMeter()
    print(f"probe {a.video_id} [{start}, {end}] offsets={a.start is not None} "
          f"effort={a.effort} timeout={a.timeout}s")  # fmt: skip
    began = time.perf_counter()
    try:
        result = await llm.transcribe(
            "transcribe",
            TranscriptWindow,
            clip,
            estimate_usd=(end - start) / 60 * settings.media_est_usd_per_min,
            meter=meter,
            check=lambda out: check_window(out, window, relative_only=False),
            settings=settings,
        )
    except Exception as exc:
        print(f"FAILED {type(exc).__name__}: {exc} after {time.perf_counter() - began:.1f} s, "
              f"cost ${meter.cost_usd:.4f}")  # fmt: skip
        return
    text = check_window(result.output, window, relative_only=False)
    words = sum(len(p.text.split()) for p in text.paragraphs)
    starts = [p.start_s for p in text.paragraphs]
    print(f"OK {time.perf_counter() - began:.1f} s, cost ${meter.cost_usd:.4f}, "
          f"out {result.meta.tokens_out} tokens, {len(starts)} paragraphs, {words} words, "
          f"starts {starts[0]}..{starts[-1]}, lang {text.language}")  # fmt: skip


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("video_id")
    p.add_argument("duration", type=int)
    p.add_argument("--start", type=int)
    p.add_argument("--end", type=int)
    p.add_argument("--effort", default="low")
    p.add_argument("--timeout", type=float, default=90.0)
    asyncio.run(main(p.parse_args()))
