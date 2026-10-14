"""Opening and transcribing recordings (Media plan §D "Service", rounds 1 and 2).

Three ordinary requests, nothing after a response: open (lookups and checks, ≈ 1 s; the player
is usable at once) → transcribe (this module, under the pending doc's lease) → analyse (the
article pipeline's phase 2, unchanged). A recording is shared content: `pending_contents/` and
`contents/` hold no uid, and a second reader of the same recording pays nothing.
"""

import asyncio
import logging
import math
import resource
import sys
import time
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta

from app import llm
from app.auth import Caller
from app.config import Settings
from app.ingest.extract import build_paragraphs
from app.ingest.models import (
    USER_INGESTED,
    Media,
    PendingDoc,
    PendingParagraph,
    Stage,
    TranscriptRecord,
    WindowParagraph,
    WindowRecord,
)
from app.ingest.safe_fetch import FetchError, get_fetcher, is_transient
from app.media import mp3, urls
from app.media.openable import media_kind, media_kind_on
from app.media.refusals import NOT_REMEMBERED, MediaCapReached, MediaRefused, MediaUnavailable
from app.media.sources import (
    MediaInfo,
    apple_episode,
    estimated_duration_s,
    probe_audio,
    youtube_info,
)
from app.media.transcript import (
    TimedParagraph,
    TranscriptRefused,
    TranscriptWindow,
    Window,
    WindowText,
    assemble,
    check_window,
    is_english,
    plan_for,
    plan_windows,
)
from app.store.content_repo import get_content_store
from app.store.docstore import get_doc_store
from app.store.media_repo import get_media_day_repo, media_day_path
from app.store.pending_repo import PENDING_TTL, AnalysisFailed, NotPending, get_pending_repo
from app.store.reader_repo import ReaderRepo
from app.store.spend_repo import today_utc

log = logging.getLogger("app.media")

TRANSCRIBE_TIMEOUT_S = 150.0
LEASE = timedelta(seconds=TRANSCRIBE_TIMEOUT_S + 30)  # always outlives the run (R1)
PARALLEL_WINDOWS = 4  # YouTube; audio uses MEDIA_AUDIO_PARALLEL_WINDOWS
CEILING_FACTOR = 2  # per item, across all attempts: 2 × the expected cost (R2)
COUNTER = "media_counts"


# One audio run per instance: its bytes and in-flight windows take hundreds of MB (R9). Tried
# without waiting (2.3): a taken slot is answered 202 like a busy lease.
_AUDIO_SLOT = asyncio.Semaphore(1)


class TranscribeBusy(Exception):
    """Another request is transcribing this recording, or another podcast on this instance
    (202: the page asks again shortly)."""


@dataclass(frozen=True)
class Opened:
    content_id: str
    new: bool
    stage: Stage | None  # None: ready (analysed)


# ---------------------------------------------------------------- open


async def open_media(media: urls.Media, caller: Caller | None, settings: Settings) -> Opened:
    """POST /v1/recs/open for a recording. Raises MediaRefused, MediaCapReached,
    MediaUnavailable or llm.BudgetExceeded; a refusal about the recording is remembered for
    the day. Switches, direct .mp3 links and show pages are answered before any I/O.
    caller None is `scripts/ingest_media.py` (plan 2.4): no reader's daily slot, no growth
    slots; the lookup cap, budget and every check still apply."""
    if not media_kind_on(media_kind(media), settings):
        raise MediaRefused("media_off")
    if isinstance(media, urls.AudioFile):
        raise MediaRefused("apple_link_only")  # no title or show without a lookup (5.2)
    if isinstance(media, urls.ApplePodcast) and media.episode_id is None:
        raise MediaRefused("not_an_episode")
    content_id = urls.content_id(media)
    cached = await get_content_store().get(content_id)
    if cached is not None and cached.media is not None:
        return Opened(content_id, new=False, stage=None)
    day = today_utc()
    days = get_media_day_repo()
    if code := await days.refusal(content_id, day):
        raise MediaRefused(code)
    now = datetime.now(UTC)
    pending = await get_pending_repo().get(content_id)
    if pending is not None and pending.expire_at > now:
        if pending.refused:
            raise MediaRefused(pending.refused)
        return Opened(content_id, new=False, stage=pending.stage)

    if caller is not None and not await _reserve_slot(caller, settings, day):
        raise MediaCapReached("reader")
    try:
        info = await look_up(media, settings, day)
        await llm.check_media_budget(estimate_usd(info.duration_s, settings), settings=settings)
        stored = await get_pending_repo().create_media(  # growth slots: at …/analyse (M9)
            _pending_doc(content_id, media, info, now), now
        )
    except MediaRefused as exc:
        await _refund_slot(caller, day)
        await days.remember_refusal(content_id, exc.code, day)
        log.info("media refused", extra={"content_id": content_id, "code": exc.code})
        raise
    except asyncio.CancelledError:
        await asyncio.shield(_refund_slot(caller, day))
        raise
    except Exception:
        await _refund_slot(caller, day)
        raise
    log.info(
        "media opened",
        extra={
            "content_id": content_id,
            "kind": media_kind(media),
            "duration_s": info.duration_s,
        },
    )
    return Opened(content_id, new=True, stage=stored.stage)


async def look_up(
    media: urls.YouTube | urls.ApplePodcast, settings: Settings, day: str | None
) -> MediaInfo:
    """videos.list, or Apple's lookup then the audio head: each counts one `media_lookup` on
    `day`. day None (`ingest_media.py --dry-run`) counts nothing and writes nothing."""

    async def reserve() -> None:
        if day is not None and not await get_media_day_repo().reserve_lookup(
            day, settings.media_lookup_daily_cap
        ):
            raise MediaCapReached("lookup")

    await reserve()
    if isinstance(media, urls.YouTube):
        return await youtube_info(media.video_id, settings)
    info = await apple_episode(media.show_id, media.episode_id, settings)
    assert info.audio_url is not None
    await reserve()
    probe = await probe_audio(info.audio_url, settings, get_fetcher())
    if info.duration_s:
        return info
    duration = estimated_duration_s(probe)  # Apple gave no length; the walk measures it
    if duration > settings.media_max_audio_s:
        raise MediaRefused("too_long")
    return replace(info, duration_s=duration)


def _pending_doc(
    content_id: str,
    media: urls.YouTube | urls.ApplePodcast,
    info: MediaInfo,
    now: datetime,
) -> PendingDoc:
    if isinstance(media, urls.YouTube):
        recording = Media(
            kind="youtube",
            video_id=media.video_id,
            duration_s=info.duration_s,
            language=info.language,
        )
    else:  # language never declared: window 1 runs alone first (R8)
        recording = Media(kind="audio", audio_url=info.audio_url, duration_s=info.duration_s)
    return PendingDoc(
        content_id=content_id,
        url=media.canonical,
        final_url=media.canonical,
        title=info.title,
        site=info.site,
        source=USER_INGESTED,
        fetched_at=now.isoformat(),
        published=info.published,
        image=info.image,
        paragraphs=[],
        expire_at=now + PENDING_TTL,
        media=recording,
        stage="transcribe",
    )


def _global_path(caller: Caller, day: str) -> str | None:
    return media_day_path(day) if caller.is_anonymous else None


async def _reserve_slot(caller: Caller, settings: Settings, day: str) -> bool:
    cap = settings.anon_media_daily_cap if caller.is_anonymous else settings.media_daily_cap
    return await ReaderRepo(get_doc_store()).reserve_daily(
        COUNTER, caller.uid, day, cap, _global_path(caller, day),
        settings.anon_global_media_daily_cap,
    )  # fmt: skip


async def _refund_slot(caller: Caller | None, day: str) -> None:
    if caller is None:
        return
    await ReaderRepo(get_doc_store()).refund_daily(
        COUNTER, caller.uid, day, _global_path(caller, day)
    )


def estimate_usd(seconds: float, settings: Settings) -> float:
    return seconds / 60 * settings.media_est_usd_per_min


# ---------------------------------------------------------------- transcribe


async def transcribe_pending(content_id: str, settings: Settings) -> None:
    """POST /v1/content/{id}/transcribe: returns once the transcript is stored (or already
    was). Raises NotPending, MediaRefused, TranscribeBusy, MediaUnavailable, AnalysisFailed
    (attempts used up), llm.BudgetExceeded, TimeoutError or a model error.

    Order (5R6): cached → switch → refused → audio slot (no wait) → budget → lease → run; the
    slot is released on every exit after it is taken."""
    cached = await get_content_store().get(content_id)
    if cached is not None and cached.media is not None:
        return
    pending = await get_pending_repo().get(content_id)
    if pending is None or pending.media is None:
        raise NotPending(content_id)
    if not media_kind_on(pending.media.kind, settings):
        raise MediaRefused("media_off")  # before the lease: no mark, no attempt, no day entry
    if pending.refused:
        raise MediaRefused(pending.refused)
    if pending.stage == "analyse":
        return
    if pending.media.kind != "audio":
        await _transcribe_leased(pending, settings)
        return
    if _AUDIO_SLOT.locked():
        raise TranscribeBusy(content_id)
    await _AUDIO_SLOT.acquire()  # no await between the check and this: never waits
    try:
        await _transcribe_leased(pending, settings)
    finally:
        _AUDIO_SLOT.release()


async def _transcribe_leased(pending: PendingDoc, settings: Settings) -> None:
    assert pending.media is not None
    content_id, repo = pending.content_id, get_pending_repo()
    remaining = [
        w
        for w in plan_for(pending.media.kind, pending.media.duration_s)
        if str(w.index) not in pending.windows
    ]
    await llm.check_media_budget(
        sum(estimate_usd(w.length_s, settings) for w in remaining), settings=settings
    )  # nothing is spent on a recording that can't finish today
    status, leased = await repo.acquire(content_id, datetime.now(UTC), LEASE, stage="transcribe")
    if status == "missing" or leased is None:
        raise NotPending(content_id)
    if status == "wrong_stage":
        return
    if status == "busy":
        raise TranscribeBusy(content_id)
    if status == "exhausted":
        raise AnalysisFailed(content_id)

    run = _Run(leased, settings)
    token = leased.lease_token or ""
    try:
        async with asyncio.timeout(TRANSCRIBE_TIMEOUT_S):
            await run.go()
    except MediaRefused as exc:
        refused = None if exc.code in NOT_REMEMBERED else exc.code
        await repo.release_transcribe(
            content_id, token, failed=run.billed, cost_usd=run.take_cost(), refused=refused
        )
        await get_media_day_repo().remember_refusal(content_id, exc.code, today_utc())
        log.info("media refused", extra={"content_id": content_id, "code": exc.code})
        raise
    except asyncio.CancelledError:  # free only when nothing was billed (R2)
        await asyncio.shield(
            repo.release_transcribe(content_id, token, failed=run.billed, cost_usd=run.take_cost())
        )
        raise
    except Exception as exc:
        free = isinstance(exc, (llm.BudgetExceeded, MediaUnavailable)) and not run.billed
        await repo.release_transcribe(content_id, token, failed=not free, cost_usd=run.take_cost())
        log.warning(
            "media transcribe failed",
            extra={
                "content_id": content_id,
                "error_class": type(exc).__name__,
                "cost_usd": round(run.meter.cost_usd, 6),
            },
        )
        raise


@dataclass
class _Run:
    """One transcribe run under the lease: windows, their costs and the ceiling. For audio,
    the episode's bytes, walked and cut into one piece per window, live only for the run."""

    pending: PendingDoc
    settings: Settings
    meter: llm.MediaMeter = field(default_factory=llm.MediaMeter)
    written: float = 0.0  # meter cost already added to the pending doc
    inflight: float = 0.0  # estimates of windows sent and not yet answered
    tokens_in: int = 0
    tokens_out: int = 0
    duration_s: int = 0  # the lookup's, or for audio the walk's exact length (5R3)
    pieces: dict[int, mp3.Piece] = field(default_factory=dict)
    fingerprint: str | None = None
    timings_ms: dict[str, int] = field(default_factory=dict)

    @property
    def billed(self) -> bool:
        return self.meter.calls > 0

    def take_cost(self) -> float:
        """Meter cost not yet written to the pending doc; marks it written."""
        delta, self.written = self.meter.cost_usd - self.written, self.meter.cost_usd
        return delta

    async def go(self) -> None:
        media = self.pending.media
        assert media is not None
        started = time.perf_counter()
        if media.kind == "audio":
            windows = await self._prepare_audio(media)
        else:
            assert media.video_id
            self.duration_s = media.duration_s
            windows = plan_for(media.kind, media.duration_s)
        done: dict[int, WindowText] = {
            int(k): WindowText(
                rec.language, tuple(TimedParagraph(p.start_s, p.text) for p in rec.paragraphs)
            )
            for k, rec in self.pending.windows.items()
        }
        todo = [w for w in windows if w.index not in done]
        if media.language is None and todo and todo[0].index == 0:
            done[0] = await self._window(todo.pop(0))  # unknown language: window 1 alone (R8)
        if media.language is None and 0 in done and not is_english(done[0].language):
            raise MediaRefused("not_english")
        parallel = (
            self.settings.media_audio_parallel_windows
            if media.kind == "audio"
            else PARALLEL_WINDOWS
        )
        limit = asyncio.Semaphore(parallel)

        async def bounded(w: Window) -> None:
            async with limit:
                done[w.index] = await self._window(w)

        tasks = [asyncio.create_task(bounded(w)) for w in todo]
        try:
            await asyncio.gather(*tasks)
        except BaseException:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        self.timings_ms["windows"] = _ms_since(started) - sum(self.timings_ms.values())
        await self._finish(media, windows, done, started)

    async def _prepare_audio(self, media: Media) -> list[Window]:
        """Fetch, walk and cut the episode before any model call. The walk's length replaces
        the lookup's for the windows, the ceiling and the stored media (5R3); bytes that differ
        from the saved windows' drop them (dynamic ads)."""
        assert media.audio_url
        started = time.perf_counter()
        data = await _fetch_audio(media.audio_url, self.settings)
        self.timings_ms["fetch"] = _ms_since(started)
        started = time.perf_counter()
        walked = mp3.walk(data)
        self.duration_s = math.floor(walked.duration_s)
        if self.duration_s > self.settings.media_max_audio_s:
            raise MediaRefused("too_long")
        windows = plan_windows(self.duration_s)
        self.pieces = {p.index: p for p in mp3.split(walked, windows)}
        self.fingerprint = walked.fingerprint
        self.timings_ms["walk"] = _ms_since(started)
        if self.pending.windows and self.pending.audio_fingerprint != self.fingerprint:
            await get_pending_repo().drop_windows(
                self.pending.content_id, self.pending.lease_token or ""
            )
            log.info("media audio changed", extra={"content_id": self.pending.content_id})
            self.pending = self.pending.model_copy(
                update={"windows": {}, "audio_fingerprint": None}
            )
        return windows

    def _clip(self, window: Window) -> llm.MediaClip:
        media = self.pending.media
        assert media is not None
        if media.kind == "audio":
            return llm.AudioClip(self.pieces[window.index].data)
        assert media.video_id
        return llm.YouTubeClip(urls.YouTube(media.video_id).canonical)  # whole video (R4.3)

    async def _window(self, window: Window) -> WindowText:
        media = self.pending.media
        assert media is not None
        relative = media.kind == "audio"  # a piece's clock starts at its own zero
        estimate = estimate_usd(window.length_s, self.settings)
        ceiling = CEILING_FACTOR * estimate_usd(self.duration_s, self.settings)
        spent = self.pending.transcribe_cost_usd + self.meter.cost_usd
        if spent + self.inflight + estimate > ceiling:
            raise MediaRefused("too_costly")
        self.inflight += estimate
        try:
            result = await llm.transcribe(
                "transcribe",
                TranscriptWindow,
                self._clip(window),
                estimate_usd=estimate,
                meter=self.meter,
                check=lambda out: check_window(out, window, relative_only=relative),
                settings=self.settings,
            )
        finally:
            self.inflight -= estimate
        text = check_window(result.output, window, relative_only=relative)
        self.tokens_in += result.meta.tokens_in
        self.tokens_out += result.meta.tokens_out
        record = WindowRecord(
            language=text.language,
            paragraphs=[WindowParagraph(start_s=p.start_s, text=p.text) for p in text.paragraphs],
        )
        await get_pending_repo().save_window(
            self.pending.content_id, self.pending.lease_token or "", window.index, record,
            self.take_cost(), fingerprint=self.fingerprint,
        )  # fmt: skip
        return text

    async def _finish(
        self, media: Media, windows: list[Window], done: dict[int, WindowText], started: float
    ) -> None:
        try:
            timed = assemble([done[w.index] for w in windows])
        except TranscriptRefused as exc:
            raise MediaRefused(exc.code) from None
        built = build_paragraphs([p.text for p in timed])
        paragraphs = [
            PendingParagraph(id=b.id, text=b.text, start_s=t.start_s)
            for b, t in zip(built, timed, strict=True)
        ]
        cost = self.pending.transcribe_cost_usd + self.meter.cost_usd
        record = TranscriptRecord(
            model=self.settings.model_quality,
            prompt_version=llm.load_prompt("transcribe").version,
            windows=len(windows),
            cost_usd=round(cost, 6),
            made_at=datetime.now(UTC).isoformat(),
            tokens_in=self.tokens_in,
            tokens_out=self.tokens_out,
        )
        await get_pending_repo().finish_transcript(
            self.pending.content_id, self.pending.lease_token or "", paragraphs,
            media.model_copy(update={"transcript": record, "duration_s": self.duration_s}),
            self.take_cost(),
        )  # fmt: skip
        extra = {
            "content_id": self.pending.content_id,
            "kind": media.kind,
            "windows": len(windows),
            "paragraphs": len(paragraphs),
            "words": sum(len(p.text.split()) for p in paragraphs),
            "cost_usd": round(cost, 6),
            "transcribe_ms": _ms_since(started),
        }
        if media.kind == "audio":  # phase timings and peak memory, once per run (R9, 5R10)
            extra |= {f"{k}_ms": v for k, v in self.timings_ms.items()}
            extra["peak_rss_mb"] = _peak_rss_mb()
        log.info("media transcribed", extra=extra)


async def _fetch_audio(url: str, settings: Settings) -> bytearray:
    """The episode through the SSRF guard. A timeout, connection error, 5xx or 429 is
    MediaUnavailable (not remembered, 5R5); anything else is a refusal remembered for the day."""
    try:
        fetched = await get_fetcher().fetch_audio(url, max_bytes=settings.media_max_audio_bytes)
    except FetchError as exc:
        log.warning("audio fetch failed", extra={"error_code": exc.code, "status": exc.status})
        if is_transient(exc):
            raise MediaUnavailable("audio") from None
        raise MediaRefused("too_long" if exc.code == "too_large" else "unsupported_audio") from None
    return fetched.body


def _ms_since(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)


def _peak_rss_mb() -> int:
    """This process's peak RSS: ru_maxrss is bytes on macOS, KB on Linux (5R10). Local runs
    measure the laptop, not Cloud Run."""
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(peak / (1 << 20) if sys.platform == "darwin" else peak / 1024)
