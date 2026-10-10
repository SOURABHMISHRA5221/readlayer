"""Held-out evaluation articles: concept growth never runs on them (M2.2 plan §C.1)."""

from functools import cache
from pathlib import Path

_FILE = Path(__file__).parents[1] / "data" / "heldout_hashes.txt"


@cache
def heldout_ids() -> frozenset[str]:
    lines = _FILE.read_text(encoding="utf-8").splitlines() if _FILE.exists() else []
    return frozenset(line.strip() for line in lines if line.strip() and not line.startswith("#"))


def is_heldout(content_id: str) -> bool:
    return content_id in heldout_ids()
