"""Keep this instance's graph and catalog up to date with concepts grown anywhere (M2.2 §C.4).

Every concept grown online is stored in `graph_growth/` (app/store/growth_repo.py). This module:
- merges all of them into the graph at startup (`load_startup`);
- adds a concept grown by this instance at once (`apply`);
- at most once per GROWTH_REFRESH_S, on a content read, queries growth docs added since the last
  one seen minus an overlap window (`maybe_refresh`): late commits and clock skew can't hide a
  doc, since `added_at` is the store's own clock and `last_seen` is the largest one seen;
- makes sure the article each growth doc came from is in this instance's catalog, retrying until
  the article lands (growth docs are written before it), for up to a day.
The graph is replaced, never mutated: `ConceptGraph.with_concepts` returns a new graph and its
version gains a growth counter (`<file version>+g<n>`), which derived caches key on.
No LLM anywhere here; one small Firestore query per interval per instance.
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta

from app.config import get_settings
from app.content import catalog
from app.graph.graph import ConceptGraph
from app.graph.loader import get_graph, set_graph
from app.graph.models import Concept
from app.store.content_repo import get_content_store
from app.store.growth_repo import GrownConcept, get_growth_repo

log = logging.getLogger("app.graph.refresh")

OVERLAP = timedelta(seconds=120)
UNRESOLVED_TTL_S = 24 * 3600.0
SOON_S = 5.0  # a page links a concept grown elsewhere a moment ago (M9 G8)


class Refresher:
    def __init__(self) -> None:
        self.base_version: str | None = None
        self.generation = 0
        self.last_seen: datetime | None = None
        self.last_check = float("-inf")
        self.unresolved: dict[str, float] = {}  # source content id -> first seen (monotonic)
        self._lock = asyncio.Lock()

    def apply(self, concepts: list[Concept]) -> ConceptGraph:
        """Add concepts (grown here or picked up) to the process graph, copy-on-write."""
        graph = get_graph()
        fresh = [c for c in concepts if graph.get(c.id) is None]
        if not fresh:
            return graph
        if self.base_version is None:
            self.base_version = graph.version.split("+g")[0]
        self.generation += 1
        new = graph.with_concepts(fresh, f"{self.base_version}+g{self.generation}")
        set_graph(new)
        log.info("graph grew", extra={"added": len(fresh), "version": new.version})
        return new

    def _seen(self, rows: list[GrownConcept]) -> None:
        stamps = [r.added_at for r in rows if isinstance(r.added_at, datetime)]
        if stamps:
            newest = max(stamps)
            self.last_seen = newest if self.last_seen is None else max(self.last_seen, newest)
        now = time.monotonic()
        for r in rows:
            if r.source_cid and catalog.missing(r.source_cid):
                self.unresolved.setdefault(r.source_cid, now)

    async def load_startup(self) -> int:
        rows = await get_growth_repo().since(None)
        self.apply([r.concept for r in rows])
        self._seen(rows)
        self.last_check = time.monotonic()
        return len(rows)

    async def maybe_refresh(self, soon: bool = False) -> None:
        """At most once per GROWTH_REFRESH_S; `soon` (a page links a concept not loaded here
        yet) shortens that to SOON_S, so an id that never appears costs a read every few
        seconds at most."""
        interval = SOON_S if soon else get_settings().growth_refresh_s
        if time.monotonic() - self.last_check < interval:
            return
        async with self._lock:
            if time.monotonic() - self.last_check < interval:
                return
            self.last_check = time.monotonic()
            try:
                after = self.last_seen - OVERLAP if self.last_seen else None
                rows = await get_growth_repo().since(after)
                self.apply([r.concept for r in rows])
                self._seen(rows)
                await self._resolve()
            except Exception as exc:  # a refresh failure must never break a read
                log.warning("growth refresh failed", extra={"error_class": type(exc).__name__})

    async def _resolve(self) -> None:
        store, now = get_content_store(), time.monotonic()
        for cid, first in list(self.unresolved.items()):
            if not catalog.missing(cid):
                del self.unresolved[cid]
            elif (doc := await store.get(cid)) is not None:
                catalog.add(doc)
                del self.unresolved[cid]
            elif now - first > UNRESOLVED_TTL_S:
                del self.unresolved[cid]


_refresher = Refresher()


def get_refresher() -> Refresher:
    return _refresher


def reset() -> None:
    """Tests: forget all refresh state."""
    global _refresher
    _refresher = Refresher()
