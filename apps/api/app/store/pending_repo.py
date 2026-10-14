"""Articles fetched but not yet analysed, Firestore `pending_contents/{url_hash}`.

Two-phase "Open here": phase 1 stores the extracted article here so the reader sees it at once;
phase 2 (POST /v1/content/{id}/analyse) takes a lease, runs demand extraction and linking, writes
`contents/` and deletes the pending doc. The lease is taken in a transaction so only one instance
spends on an article; it outlives the analysis timeout, so an expired lease always means the
earlier run has already stopped. Shared content, no user data: outside export and delete.
"""

import contextlib
import secrets
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, Literal

from app.ingest.models import Media, PendingDoc, PendingParagraph, Stage, WindowRecord
from app.store.docstore import DocStore, Txn, get_doc_store

COLLECTION = "pending_contents"
PENDING_TTL = timedelta(hours=24)
MAX_ATTEMPTS = 3

# "wrong_stage": a recording still being transcribed asked to analyse, or the reverse.
Acquire = Literal["acquired", "busy", "missing", "exhausted", "wrong_stage"]


class LeaseLost(Exception):
    """This run's lease expired and another run took it: nothing more may be written."""


class AnalysisBusy(Exception):
    """Another request holds the lease on this article's analysis."""


class AnalysisFailed(Exception):
    """This article's analysis failed MAX_ATTEMPTS times; it won't be retried."""


class ContentTranscribing(Exception):
    """A recording asked to analyse before its transcript exists (409, never an attempt)."""


class NotPending(Exception):
    """No pending doc (and no content) for this id."""


def _path(content_id: str) -> str:
    return f"{COLLECTION}/{content_id}"


class PendingRepo:
    def __init__(self, store: DocStore) -> None:
        self._store = store

    async def get(self, content_id: str) -> PendingDoc | None:
        data = await self._store.get(_path(content_id))
        return PendingDoc.model_validate(data) if data else None

    async def create(self, doc: PendingDoc) -> PendingDoc:
        """Store a freshly extracted article unless another request already did; returns the
        stored one either way (its paragraphs are the ones every reader sees)."""

        async def body(txn: Txn) -> PendingDoc:
            existing = await txn.get(_path(doc.content_id))
            if existing:
                return PendingDoc.model_validate(existing)
            txn.set(_path(doc.content_id), doc.model_dump())
            return doc

        return await self._store.run(body)

    async def create_media(self, doc: PendingDoc, now: datetime) -> PendingDoc:
        """Store a recording at stage "transcribe", or overwrite one past `expire_at` (the TTL
        can lag a day); any other existing doc, refused ones included, is returned unchanged."""

        async def body(txn: Txn) -> PendingDoc:
            existing = await txn.get(_path(doc.content_id))
            if existing:
                current = PendingDoc.model_validate(existing)
                if current.expire_at > now:
                    return current
            txn.set(_path(doc.content_id), doc.model_dump())
            return doc

        return await self._store.run(body)

    async def acquire(
        self, content_id: str, now: datetime, lease: timedelta, stage: Stage = "analyse"
    ) -> tuple[Acquire, PendingDoc | None]:
        """Take the lease for `stage`; only that stage's attempts count toward MAX_ATTEMPTS."""

        async def body(txn: Txn) -> tuple[Acquire, PendingDoc | None]:
            data = await txn.get(_path(content_id))
            if not data:
                return "missing", None
            doc = PendingDoc.model_validate(data)
            if doc.stage != stage:
                return "wrong_stage", doc
            attempts = doc.attempts if stage == "analyse" else doc.transcribe_attempts
            if attempts >= MAX_ATTEMPTS:
                return "exhausted", doc
            if doc.lease_until is not None and doc.lease_until > now:
                return "busy", doc
            update = {"lease_until": now + lease, "lease_token": secrets.token_hex(8)}
            leased = doc.model_copy(update=update)
            txn.set(_path(content_id), leased.model_dump())
            return "acquired", leased

        return await self._store.run(body)

    async def save_window(
        self, content_id: str, token: str, index: int, record: WindowRecord, cost_usd: float,
        fingerprint: str | None = None,
    ) -> None:  # fmt: skip
        """One finished window and what it cost; an audio window also writes the fingerprint
        of the bytes it came from. Raises LeaseLost (the cost is still added)."""

        def update(doc: PendingDoc) -> dict[str, Any]:
            changes: dict[str, Any] = {"windows": {**doc.windows, str(index): record}}
            return changes | ({"audio_fingerprint": fingerprint} if fingerprint else {})

        await self._media_write(content_id, token, cost_usd, update)

    async def drop_windows(self, content_id: str, token: str) -> None:
        """Forget the saved windows (their cost stays counted): the audio changed (5R3).
        Raises LeaseLost."""

        def update(_doc: PendingDoc) -> dict[str, Any]:
            return {"windows": {}, "audio_fingerprint": None}

        await self._media_write(content_id, token, 0.0, update)

    async def finish_transcript(
        self, content_id: str, token: str, paragraphs: list[PendingParagraph], media: Media,
        cost_usd: float,
    ) -> PendingDoc:  # fmt: skip
        """The transcript is the text now: stage "analyse", phase 2's counter fresh, lease
        dropped, the per-window copies no longer needed. Raises LeaseLost."""

        def update(doc: PendingDoc) -> dict[str, Any]:
            return {
                "paragraphs": paragraphs,
                "media": media,
                "stage": "analyse",
                "attempts": 0,
                "lease_until": None,
                "lease_token": None,
                "windows": {},
                "audio_fingerprint": None,
            }

        return await self._media_write(content_id, token, cost_usd, update)

    async def release_transcribe(
        self, content_id: str, token: str, *, failed: bool, cost_usd: float,
        refused: str | None = None,
    ) -> None:  # fmt: skip
        """Drop the lease; `failed` counts an attempt (any run that billed a call, R2);
        `refused` keeps the code on the doc until it expires (plan 2.2)."""

        def update(doc: PendingDoc) -> dict[str, Any]:
            return {
                "lease_until": None,
                "lease_token": None,
                "transcribe_attempts": doc.transcribe_attempts + (1 if failed else 0),
                **({"refused": refused} if refused else {}),
            }

        with contextlib.suppress(LeaseLost):  # another run holds it; the cost was still added
            await self._media_write(content_id, token, cost_usd, update)

    async def _media_write(
        self,
        content_id: str,
        token: str,
        cost_usd: float,
        update: Callable[[PendingDoc], dict[str, Any]],
    ) -> PendingDoc:
        async def body(txn: Txn) -> tuple[PendingDoc | None, bool]:
            data = await txn.get(_path(content_id))
            if not data:
                return None, False
            doc = PendingDoc.model_validate(data)
            ours = doc.lease_token == token
            changes: dict[str, Any] = {"transcribe_cost_usd": doc.transcribe_cost_usd + cost_usd}
            if ours:
                changes |= update(doc)
            new = PendingDoc.model_validate(doc.model_dump() | _dump(changes))
            txn.set(_path(content_id), new.model_dump())
            return new, ours

        doc, ours = await self._store.run(body)
        if doc is None or not ours:
            raise LeaseLost(content_id)
        return doc

    async def release(self, content_id: str, *, failed: bool) -> None:
        """Drop the lease; `failed` counts the attempt (an analysis that ran and failed)."""

        async def body(txn: Txn) -> None:
            data = await txn.get(_path(content_id))
            if not data:
                return
            doc = PendingDoc.model_validate(data)
            update = {"lease_until": None, "attempts": doc.attempts + (1 if failed else 0)}
            txn.set(_path(content_id), doc.model_copy(update=update).model_dump())

        await self._store.run(body)

    async def delete(self, content_id: str) -> None:
        async def body(txn: Txn) -> None:
            txn.delete(_path(content_id))

        await self._store.run(body)


def _dump(changes: dict[str, Any]) -> dict[str, Any]:
    def plain(value: Any) -> Any:
        if hasattr(value, "model_dump"):
            return value.model_dump()
        if isinstance(value, list):
            return [plain(v) for v in value]
        if isinstance(value, dict):
            return {k: plain(v) for k, v in value.items()}
        return value

    return {k: plain(v) for k, v in changes.items()}


def get_pending_repo() -> PendingRepo:
    return PendingRepo(get_doc_store())
