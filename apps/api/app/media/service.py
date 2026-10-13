"""Opening and transcribing recordings (Media plan §D "Service", rounds 1 and 2).

Three ordinary requests, nothing after a response: open (lookups and checks, ≈ 1 s; the player
is usable at once) → transcribe (this module, under the pending doc's lease) → analyse (the
article pipeline's phase 2, unchanged). A recording is shared content: `pending_contents/` and
`contents/` hold no uid, and a second reader of the same recording pays nothing.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from app import llm
from app.auth import Caller
from app.config import Settings
from app.ingest import quota
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
from app.media import urls
from app.media.refusals import MediaCapReached, MediaRefused
from app.media.sources import MediaInfo, youtube_info
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
PARALLEL_WINDOWS = 4
CEILING_FACTOR = 2  # per item, across all attempts: 2 × the expected cost (R2)
COUNTER = "media_counts"


class TranscribeBusy(Exception):
    """Another request is transcribing this recording (202: the page asks again shortly)."""


@dataclass(frozen=True)
class Opened:
    content_id: str
    new: bool
    stage: Stage | None  # None: ready (analysed)


# ---------------------------------------------------------------- open


async def open_media(media: urls.Media, caller: Caller, settings: Settings) -> Opened:
    """POST /v1/recs/open for a recording. Raises MediaRefused, MediaCapReached,
    MediaUnavailable or llm.BudgetExceeded; a refusal is remembered for the day."""
    if not settings.media_enabled or not isinstance(media, urls.YouTube):
        raise MediaRefused("media_off")  # podcasts arrive with the plan's step 6
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

    if not await _reserve_slot(caller, settings, day):
        raise MediaCapReached("reader")
    try:
        if not await days.reserve_lookup(day, settings.media_lookup_daily_cap):
            raise MediaCapReached("lookup")
        info = await youtube_info(media.video_id, settings)
        await llm.check_media_budget(_estimate(info.duration_s, settings), settings=settings)
        slots = await quota.reserve_growth(caller, settings)
        stored = await get_pending_repo().create_media(
            _pending_doc(content_id, media, info, slots, now), now
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
        extra={"content_id": content_id, "kind": "youtube", "duration_s": info.duration_s},
    )
    return Opened(content_id, new=True, stage=stored.stage)


def _pending_doc(
    content_id: str, media: urls.YouTube, info: MediaInfo, grow_slots: int, now: datetime
) -> PendingDoc:
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
        grow_slots=grow_slots,
        expire_at=now + PENDING_TTL,
        media=Media(
            kind="youtube",
            video_id=media.video_id,
            duration_s=info.duration_s,
            language=info.language,
        ),
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


async def _refund_slot(caller: Caller, day: str) -> None:
    await ReaderRepo(get_doc_store()).refund_daily(
        COUNTER, caller.uid, day, _global_path(caller, day)
    )


def _estimate(seconds: float, settings: Settings) -> float:
    return seconds / 60 * settings.media_est_usd_per_min


# ---------------------------------------------------------------- transcribe


async def transcribe_pending(content_id: str, settings: Settings) -> None:
    """POST /v1/content/{id}/transcribe: returns once the transcript is stored (or already
    was). Raises NotPending, MediaRefused, TranscribeBusy, AnalysisFailed (attempts used up),
    llm.BudgetExceeded, TimeoutError or a model error."""
    cached = await get_content_store().get(content_id)
    if cached is not None and cached.media is not None:
        return
    repo = get_pending_repo()
    pending = await repo.get(content_id)
    if pending is None or pending.media is None:
        raise NotPending(content_id)
    if pending.refused:
        raise MediaRefused(pending.refused)
    if pending.stage == "analyse":
        return
    remaining = [
        w
        for w in plan_for(pending.media.kind, pending.media.duration_s)
        if str(w.index) not in pending.windows
    ]
    await llm.check_media_budget(
        sum(_estimate(w.length_s, settings) for w in remaining), settings=settings
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
        await repo.release_transcribe(
            content_id, token, failed=run.billed, cost_usd=run.take_cost(), refused=exc.code
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
        free = isinstance(exc, llm.BudgetExceeded) and not run.billed
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
    """One transcribe run under the lease: windows, their costs and the ceiling."""

    pending: PendingDoc
    settings: Settings
    meter: llm.MediaMeter = field(default_factory=llm.MediaMeter)
    written: float = 0.0  # meter cost already added to the pending doc
    inflight: float = 0.0  # estimates of windows sent and not yet answered
    tokens_in: int = 0
    tokens_out: int = 0

    @property
    def billed(self) -> bool:
        return self.meter.calls > 0

    def take_cost(self) -> float:
        """Meter cost not yet written to the pending doc; marks it written."""
        delta, self.written = self.meter.cost_usd - self.written, self.meter.cost_usd
        return delta

    async def go(self) -> None:
        media = self.pending.media
        assert media is not None and media.kind == "youtube" and media.video_id
        started = time.perf_counter()
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
        limit = asyncio.Semaphore(PARALLEL_WINDOWS)

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
        await self._finish(media, windows, done, started)

    async def _window(self, window: Window) -> WindowText:
        media = self.pending.media
        assert media is not None and media.video_id
        estimate = _estimate(window.length_s, self.settings)
        ceiling = CEILING_FACTOR * _estimate(media.duration_s, self.settings)
        spent = self.pending.transcribe_cost_usd + self.meter.cost_usd
        if spent + self.inflight + estimate > ceiling:
            raise MediaRefused("too_costly")
        self.inflight += estimate
        try:
            result = await llm.transcribe(
                "transcribe",
                TranscriptWindow,
                llm.YouTubeClip(urls.YouTube(media.video_id).canonical),  # whole video (R4.3)
                estimate_usd=estimate,
                meter=self.meter,
                check=lambda out: check_window(out, window, relative_only=False),
                settings=self.settings,
            )
        finally:
            self.inflight -= estimate
        text = check_window(result.output, window, relative_only=False)
        self.tokens_in += result.meta.tokens_in
        self.tokens_out += result.meta.tokens_out
        record = WindowRecord(
            language=text.language,
            paragraphs=[WindowParagraph(start_s=p.start_s, text=p.text) for p in text.paragraphs],
        )
        await get_pending_repo().save_window(
            self.pending.content_id, self.pending.lease_token or "", window.index, record,
            self.take_cost(),
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
            media.model_copy(update={"transcript": record}), self.take_cost(),
        )  # fmt: skip
        log.info(
            "media transcribed",
            extra={
                "content_id": self.pending.content_id,
                "windows": len(windows),
                "paragraphs": len(paragraphs),
                "words": sum(len(p.text.split()) for p in paragraphs),
                "cost_usd": round(cost, 6),
                "transcribe_ms": round((time.perf_counter() - started) * 1000),
            },
        )
