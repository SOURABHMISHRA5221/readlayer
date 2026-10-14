"""Stored pages a reader's reopen would grow after the M9 deploy (plan G11). Read only.

    uv run python -m scripts.growth_backlog --dry-run

Lists, by source, the pages `needs_growth` says yes to, the slots they would ask for (≤ 5 each)
and the worst-case cost: one growth run per page at $0.0050 mean and $0.0127 dearest (measured
for decision 53). Firestore reads only; prints the target database first.
"""

import argparse
import asyncio
import os
import sys
from collections import Counter
from dataclasses import dataclass

from app.config import get_settings
from app.graph.growth_need import needs_growth, untried_count
from app.graph.heldout import is_heldout
from app.store.content_repo import ContentStore, get_content_store

MEAN_RUN_USD = 0.0050
DEAREST_RUN_USD = 0.0127


@dataclass(frozen=True)
class Backlog:
    scanned: int
    pages: dict[str, int]
    slots: int

    @property
    def mean_usd(self) -> float:
        return round(sum(self.pages.values()) * MEAN_RUN_USD, 4)

    @property
    def worst_usd(self) -> float:
        return round(sum(self.pages.values()) * DEAREST_RUN_USD, 4)


async def count(store: ContentStore) -> Backlog:
    per_article = get_settings().growth_per_article
    pages: Counter[str] = Counter()
    scanned = slots = 0
    async for doc in store.iter_all():
        scanned += 1
        if needs_growth(doc, heldout=is_heldout(doc.content_id)):
            pages[doc.source] += 1
            slots += untried_count(doc.demands, frozenset(doc.grow_tried), per_article)
    return Backlog(scanned, dict(pages), slots)


async def main() -> int:
    host = os.environ.get("FIRESTORE_EMULATOR_HOST")
    project = get_settings().db_project
    print(f"target: {'emulator ' + host if host else 'PRODUCTION'} ({project}), read only")
    report = await count(get_content_store())
    print(f"scanned {report.scanned} stored pages")
    print(f"would grow on reopen: {report.pages or 'none'}, asking for ≤ {report.slots} slots")
    print(f"worst case: ${report.mean_usd} at the mean run, ${report.worst_usd} at the dearest")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", required=True, help="read only")
    parser.parse_args()
    sys.exit(asyncio.run(main()))
