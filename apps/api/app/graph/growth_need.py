"""Which stored pages a reader's reopen should grow (M9 part 1), pure and light: the read path
imports it (GET /v1/content says `grow_pending`), so it loads no LLM or ingestion library."""

from collections.abc import Sequence

from app.graph.build import normalize_label
from app.ingest.models import NOT_CORPUS, ContentDoc, Demand

# Demand types that link by embedding, and that growth may add concepts for.
EMBED_TYPES = frozenset({"concept", "term"})
# Calls that only growth makes: a stored page that has one was grown (the old-page rule).
GROWTH_TASKS = frozenset({"concept_define", "link_merge", "concept_prereqs"})


def untried_groups(demands: Sequence[Demand], exclude: frozenset[str]) -> dict[str, list[Demand]]:
    """Unlinked concept/term demands grouped by normalised label, minus labels already tried."""
    groups: dict[str, list[Demand]] = {}
    for d in demands:
        key = normalize_label(d.label)
        if d.type in EMBED_TYPES and d.target_id is None and key and key not in exclude:
            groups.setdefault(key, []).append(d)
    return groups


def untried_count(demands: Sequence[Demand], tried: frozenset[str], limit: int) -> int:
    """How many labels growth would try on this page now (what phase 2 and /grow reserve)."""
    return min(len(untried_groups(demands, tried)), max(0, limit))


def needs_growth(doc: ContentDoc, *, heldout: bool) -> bool:
    """A stored page a reader's reopen should grow (G1–G3). Only a reader's own pages
    (NOT_CORPUS), never held out, with an untried label. Pages stored before M9 (no flag): an
    extension page that was never grown and isn't a recording."""
    if heldout or doc.source not in NOT_CORPUS:
        return False
    if not untried_count(doc.demands, frozenset(doc.grow_tried), 1):
        return False
    if doc.grow_pending is not None:
        return doc.grow_pending
    grown = any(c.task in GROWTH_TASKS for c in doc.llm_calls)
    return doc.source == "extension" and doc.media is None and not grown
