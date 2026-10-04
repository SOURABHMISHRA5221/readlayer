"""Daily LLM spend ledger used by the budget guard in app/llm.py.

Layout: ops/spend/days/{yyyy-mm-dd} (UTC) with summed cost, tokens and call count.
"""

from datetime import UTC, datetime
from typing import Protocol

from google.cloud import firestore


def today_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


class SpendStore(Protocol):
    async def get_today(self) -> float: ...

    async def add(self, cost_usd: float, tokens_in: int, tokens_out: int) -> None: ...


class FirestoreSpendStore:
    def __init__(self, project: str) -> None:
        self._db = firestore.AsyncClient(project=project or None)

    def _doc(self) -> firestore.AsyncDocumentReference:
        return self._db.collection("ops").document("spend").collection("days").document(today_utc())

    async def get_today(self) -> float:
        snap = await self._doc().get()
        return float((snap.to_dict() or {}).get("cost_usd", 0.0)) if snap.exists else 0.0

    async def add(self, cost_usd: float, tokens_in: int, tokens_out: int) -> None:
        await self._doc().set(
            {
                "cost_usd": firestore.Increment(cost_usd),
                "tokens_in": firestore.Increment(tokens_in),
                "tokens_out": firestore.Increment(tokens_out),
                "calls": firestore.Increment(1),
                "updated_at": firestore.SERVER_TIMESTAMP,
            },
            merge=True,
        )


class InMemorySpendStore:
    """For tests and local runs without Firestore."""

    def __init__(self, initial_usd: float = 0.0) -> None:
        self.total = initial_usd
        self.calls = 0

    async def get_today(self) -> float:
        return self.total

    async def add(self, cost_usd: float, tokens_in: int, tokens_out: int) -> None:
        self.total += cost_usd
        self.calls += 1
