"""Daily LLM spend ledger used by the budget guard in app/llm.py.

Layout: ops/spend/days/{yyyy-mm-dd} (UTC) with summed cost, tokens, call count and
`llm_fallbacks` (so a silent quality drop shows up).
"""

from datetime import UTC, datetime
from typing import Protocol

from google.cloud import firestore


def today_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


class SpendStore(Protocol):
    async def get_today(self) -> float: ...

    async def get_media_today(self) -> float: ...

    async def add(
        self, cost_usd: float, tokens_in: int, tokens_out: int, *, media: bool = False
    ) -> None: ...

    async def add_fallback(self) -> None: ...


class FirestoreSpendStore:
    def __init__(self, project: str) -> None:
        self._db = firestore.AsyncClient(project=project or None)

    def _doc(self) -> firestore.AsyncDocumentReference:
        return self._db.collection("ops").document("spend").collection("days").document(today_utc())

    async def get_today(self) -> float:
        return await self._field("cost_usd")

    async def get_media_today(self) -> float:
        return await self._field("media_usd")

    async def _field(self, name: str) -> float:
        snap = await self._doc().get()
        return float((snap.to_dict() or {}).get(name, 0.0)) if snap.exists else 0.0

    async def add(
        self, cost_usd: float, tokens_in: int, tokens_out: int, *, media: bool = False
    ) -> None:
        """`media` calls count in `cost_usd` (the $8 guard) and again in `media_usd`."""
        fields = {
            "cost_usd": firestore.Increment(cost_usd),
            "tokens_in": firestore.Increment(tokens_in),
            "tokens_out": firestore.Increment(tokens_out),
            "calls": firestore.Increment(1),
            "updated_at": firestore.SERVER_TIMESTAMP,
        }
        if media:
            fields["media_usd"] = firestore.Increment(cost_usd)
        await self._doc().set(fields, merge=True)

    async def add_fallback(self) -> None:
        await self._doc().set({"llm_fallbacks": firestore.Increment(1)}, merge=True)


class InMemorySpendStore:
    """For tests and local runs without Firestore."""

    def __init__(self, initial_usd: float = 0.0, media_usd: float = 0.0) -> None:
        self.total = initial_usd
        self.media = media_usd
        self.calls = 0
        self.fallbacks = 0

    async def get_today(self) -> float:
        return self.total

    async def get_media_today(self) -> float:
        return self.media

    async def add(
        self, cost_usd: float, tokens_in: int, tokens_out: int, *, media: bool = False
    ) -> None:
        self.total += cost_usd
        self.calls += 1
        if media:
            self.media += cost_usd

    async def add_fallback(self) -> None:
        self.fallbacks += 1
