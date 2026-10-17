"""Warm the slow lazy imports off the notes' critical path (decision 69 C).

LiteLLM (the first model call) and spaCy (the first parse) load lazily so cold starts stay short
(STATUS §5). The first analysis on an instance used to pay both inside the reader's wait: 11–17 s
before its first model call. Startup starts them in a thread without waiting (decision 69 C2: on
link open alone the live wait was still ≈ 7.5 s), opening a link starts them too, and analysis
waits for them off the event loop. Run once per process. No model call, no spend.
"""

import asyncio
import logging
import threading
import time

from app import llm

log = logging.getLogger("app.warm")

_lock = threading.Lock()
_done = False
_tasks: set[asyncio.Future[None]] = set()  # fire-and-forget tasks, held until they finish


def real_warm() -> None:
    """Run once per process; later and concurrent calls return when the first one is done."""
    global _done
    with _lock:
        if _done:
            return
        start = time.perf_counter()
        try:
            from app.ingest import features  # here, not at import: importing the app stays light

            llm._litellm()
            features._nlp()
        except Exception as exc:  # the first model call or parse then loads it, as before
            log.warning("warm-up failed", extra={"error_class": type(exc).__name__})
        else:
            log.info(
                "warm-up done", extra={"warm_ms": round((time.perf_counter() - start) * 1000, 1)}
            )
        _done = True


warm = real_warm  # tests replace this with a no-op (tests/conftest.py)


def start() -> None:
    """Begin warming in a thread without waiting (phase 1)."""
    task = asyncio.ensure_future(asyncio.to_thread(warm))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def ready() -> None:
    """Wait for the warm-up in a thread, so the event loop never blocks on an import lock."""
    await asyncio.to_thread(warm)


def reset() -> None:
    """Tests only."""
    global _done
    with _lock:
        _done = False
