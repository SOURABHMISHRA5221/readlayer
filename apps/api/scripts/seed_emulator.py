"""Seed the local Firestore emulator for `make dev-emulator` (M7 harness). Reads production,
writes only to the emulator.

    FIRESTORE_EMULATOR_HOST=127.0.0.1:8085 uv run python -m scripts.seed_emulator

Copies a few library articles, the three persona templates and today's LLM spend ledger (so the
budget guard sees the real day's spend) from production into the emulator's demo project, then
prints the harness budget: today's production spend + min(1, cap − that spend), since the
emulator ledger starts from the copied spend. Two separate clients: the
production one is built with the emulator variable removed from the environment; the emulator
one is built for project `demo-readlayer` with the emulator host asserted. Refuses to run if
both would point at the same target.
"""

import asyncio
import os
from typing import Any

from google.cloud import firestore

from app.store.spend_repo import today_utc

PROD_PROJECT = "readlayer-sourabh-26"
EMULATOR_PROJECT = "demo-readlayer"
DAILY_CAP_USD = 8.0
HARNESS_MAX_USD = 1.0
ARTICLES = (
    "2332418841faa08d5f5e157c2d038d1d",  # ET markets preview
    "99a2cb53f16256bd275bafd180364134",  # Guardian, Polymarket bets on HSBC
    "1bff839e2ef3b017b35a89fce1653a26",  # ET, RoDTEP extension
    "628d6fd2aa9fd3b5a99cedb64c70aa93",  # ET, volatility / credit spreads (eval G05)
    "e8aa9578974ed73ff4f0b22650cae478",  # Guardian, UK bond yields (eval G13)
)
PERSONAS = ("newcomer", "trader", "policy_student")


def _clients() -> tuple[firestore.AsyncClient, firestore.AsyncClient]:
    host = os.environ.get("FIRESTORE_EMULATOR_HOST", "")
    if not host.startswith(("127.0.0.1:", "localhost:")):
        raise SystemExit("FIRESTORE_EMULATOR_HOST must point at a local emulator")
    del os.environ["FIRESTORE_EMULATOR_HOST"]
    try:
        prod = firestore.AsyncClient(project=PROD_PROJECT)
    finally:
        os.environ["FIRESTORE_EMULATOR_HOST"] = host
    emulator = firestore.AsyncClient(project=EMULATOR_PROJECT)
    if prod.project == emulator.project or getattr(prod, "_emulator_host", None):
        raise SystemExit("refusing: production and emulator clients point at the same target")
    if not getattr(emulator, "_emulator_host", None):
        raise SystemExit("refusing: the emulator client is not using the emulator")
    return prod, emulator


async def _copy(prod: Any, emu: Any, path: str) -> bool:
    snap = await prod.document(path).get()
    if not snap.exists:
        print(f"  missing in production: {path}")
        return False
    await emu.document(path).set(snap.to_dict())
    return True


async def main() -> None:
    prod, emu = _clients()
    day = today_utc()
    copied = 0
    for cid in ARTICLES:
        copied += await _copy(prod, emu, f"contents/{cid}")
    for persona in PERSONAS:
        copied += await _copy(prod, emu, f"persona_templates/{persona}")
    spend_snap = await prod.document(f"ops/spend/days/{day}").get()
    spend = float((spend_snap.to_dict() or {}).get("cost_usd", 0.0)) if spend_snap.exists else 0.0
    if spend_snap.exists:
        await emu.document(f"ops/spend/days/{day}").set(spend_snap.to_dict())
    # The emulator ledger starts at today's production spend, so its cap is that spend plus the
    # harness allowance: new harness spend ≤ min($1, $8 − today's spend).
    allowance = max(0.0, min(HARNESS_MAX_USD, DAILY_CAP_USD - spend))
    print(f"seeded {copied} docs into {EMULATOR_PROJECT}; production spend today ${spend:.4f}")
    print(f"harness allowance ${allowance:.4f}")
    print(f"HARNESS_BUDGET_USD={spend + allowance:.4f}")


if __name__ == "__main__":
    asyncio.run(main())
