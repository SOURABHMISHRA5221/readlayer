"""Pre-warm recordings for the demo (Media plan R12, 2.4): open, transcribe and analyse through
the same service as the API, so a demo reader who opens one later pays nothing.

Run from apps/api:
    uv run python -m scripts.ingest_media <url>... --dry-run
    uv run python -m scripts.ingest_media <url>...

--dry-run: classification, the lookups' checks, the window plan and the cost estimate; no model
call and no write (lookups are not counted). A real run stores each transcript with source
`user_ingested` (never corpus) and no reader: no daily slot, no growth slots, no `ingested`
entry. Writes go wherever the environment points (FIRESTORE_EMULATOR_HOST or production);
the target is printed first. At most MAX_RECORDINGS per run (plan "Production writes").
"""

import argparse
import asyncio
import os
import sys
import time

from app import llm
from app.config import Settings, get_settings
from app.graph.loader import get_graph, load_serving_graph
from app.ingest.service import analyse_pending
from app.media import urls
from app.media.openable import media_kind, media_kind_on
from app.media.refusals import MediaCapReached, MediaRefused, MediaUnavailable, message
from app.media.service import TranscribeBusy, estimate_usd, look_up, open_media, transcribe_pending
from app.media.transcript import plan_for
from app.store.content_repo import get_content_store
from app.store.pending_repo import get_pending_repo

MAX_RECORDINGS = 6
TRANSCRIBE_TRIES = 3  # a podcast slot held by the API instance answers busy; wait and retry
BUSY_WAIT_S = 30
SKIPPABLE = (MediaRefused, MediaCapReached, MediaUnavailable)


def describe(exc: Exception) -> str:
    code = getattr(exc, "code", None)
    return f"{code}: {message(code)}" if isinstance(exc, MediaRefused) else f"{type(exc).__name__}"


def target(settings: Settings) -> str:
    if host := os.environ.get("FIRESTORE_EMULATOR_HOST"):
        return f"emulator {host} ({settings.db_project})"
    return f"PRODUCTION {settings.db_project}"


async def dry_run(url: str, settings: Settings) -> None:
    media = urls.classify(url)
    if media is None:
        print(f"  not a recording: {url}")
        return
    kind = media_kind(media)
    content_id = urls.content_id(media)
    print(f"  {kind} {content_id}  {media.canonical}")
    if await get_content_store().get(content_id) is not None:
        print("  already stored: a real run costs nothing")
        return
    if not media_kind_on(kind, settings):
        print(f"  refused media_off: {message('media_off')}")
        return
    if not isinstance(media, urls.YouTube | urls.ApplePodcast) or (
        isinstance(media, urls.ApplePodcast) and media.episode_id is None
    ):
        print("  refused: Apple episode links and YouTube videos only")
        return
    try:
        info = await look_up(media, settings, day=None)
    except SKIPPABLE as exc:
        print(f"  refused {describe(exc)}")
        return
    windows = plan_for("youtube" if isinstance(media, urls.YouTube) else "audio", info.duration_s)
    plan = ", ".join(f"{w.start_s}-{w.end_s}s" for w in windows)
    print(f"  ok: {info.title!r} · {info.site} · {info.duration_s} s · lang {info.language}")
    print(f"  windows: {plan}  estimate ${estimate_usd(info.duration_s, settings):.3f}")


async def transcribe(content_id: str, settings: Settings) -> None:
    for attempt in range(1, TRANSCRIBE_TRIES + 1):
        try:
            await transcribe_pending(content_id, settings)
            return
        except TranscribeBusy:
            if attempt == TRANSCRIBE_TRIES:
                raise
            print(f"  busy, waiting {BUSY_WAIT_S} s")
            await asyncio.sleep(BUSY_WAIT_S)


async def ingest(url: str, settings: Settings) -> bool:
    media = urls.classify(url)
    if media is None:
        print(f"  not a recording: {url}")
        return False
    spend = llm.get_spend_store()
    before = await spend.get_media_today()
    began = time.perf_counter()
    try:
        opened = await open_media(media, None, settings)
        print(f"  opened {opened.content_id} new={opened.new} stage={opened.stage}")
        if opened.stage is None:
            print("  already stored: nothing to do")
            return True
        await transcribe(opened.content_id, settings)
        transcribed = time.perf_counter()
        pending = await get_pending_repo().get(opened.content_id)
        if pending is not None:
            await analyse_pending(opened.content_id)
    except SKIPPABLE as exc:
        print(f"  refused {describe(exc)}")
        return False
    doc = await get_content_store().get(opened.content_id)
    cost = await spend.get_media_today() - before
    words = sum(len(p.text.split()) for p in doc.paragraphs) if doc else 0
    print(
        f"  stored: {words} words, transcribe {transcribed - began:.1f} s, "
        f"total {time.perf_counter() - began:.1f} s, media spend +${cost:.4f}"
    )
    return doc is not None


async def graph_ready(settings: Settings) -> bool:
    """Analysis links demands against the in-memory graph, which only API startup loads. Without
    it every demand stays unlinked and the stored recording shows no notes, for good."""
    if not settings.concepts_uri:
        print("CONCEPTS_URI is not set: analysis would link nothing. Set it as the API has it.")
        return False
    grown = await load_serving_graph(settings.concepts_uri)
    if not len(get_graph()):
        print(f"the concept graph at {settings.concepts_uri} loaded empty")
        return False
    print(f"graph: {len(get_graph())} concepts ({grown} grown online)")
    return True


async def main(args: argparse.Namespace, settings: Settings | None = None) -> int:
    settings = settings or get_settings()
    if len(args.urls) > MAX_RECORDINGS:
        print(f"at most {MAX_RECORDINGS} recordings per run, got {len(args.urls)}")
        return 2
    print(f"target: {target(settings)}{'  (dry run, no writes)' if args.dry_run else ''}")
    if not args.dry_run and not await graph_ready(settings):
        return 2
    failed = 0
    for url in args.urls:
        print(url)
        if args.dry_run:
            await dry_run(url, settings)
        elif not await ingest(url, settings):
            failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("urls", nargs="+")
    parser.add_argument("--dry-run", action="store_true", help="checks and plan, no model call")
    sys.exit(asyncio.run(main(parser.parse_args())))
