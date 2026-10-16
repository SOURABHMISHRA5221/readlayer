"""Analogy frames (decision 67 A1–A2, DESIGN §7). Pure: no I/O.

A frame is the field an analogy may come from. The reader's own pick is one of THINKS_IN
(onboarding or the profile); "for you" is a field from their knowledge map: the domain where the
reading they actually did (their edges, forgetting applied) shows the most known concepts. Only
the frame word ever reaches a model (DESIGN §11).
"""

from collections.abc import Mapping
from datetime import datetime
from statistics import fmean
from typing import Literal, get_args

from app.graph.graph import ConceptGraph
from app.graph.taxonomy import DOMAIN_IDS
from app.reader import model
from app.reader.state import ReaderState, ThinksIn

# Domains with no THINKS_IN counterpart are frames by their own name.
MapFrame = Literal[
    "economics", "finance", "business", "policy", "politics", "environment", "sports", "culture",
    "society",
]  # fmt: skip
Frame = Literal[ThinksIn, MapFrame]
FRAMES: tuple[str, ...] = get_args(Frame)

DOMAIN_FRAME: Mapping[str, Frame] = {
    "economics": "economics", "finance": "finance", "business": "business", "policy": "policy",
    "politics": "politics", "law": "law", "technology": "software", "science": "science",
    "health": "medicine", "environment": "environment", "sports": "sports", "culture": "culture",
    "education": "teaching", "society": "society",
}  # fmt: skip

KNOWN_P = 0.5  # the map's and reading goals' "known" (DESIGN §15.1, §18)
MIN_KNOWN = 3


def for_you(
    state: ReaderState, graph: ConceptGraph, exclude_domain: str | None, now: datetime
) -> Frame | None:
    """The strongest domain by known concepts in the reader's edges (not the prior), ranked by
    count, then mean p, then taxonomy order; the note's own domain excluded; None if no domain
    has MIN_KNOWN."""
    known: dict[str, list[float]] = {}
    for cid, edge in state.edges.items():
        c = graph.get(cid)
        if c is None:
            continue
        p0 = model.prior(state.theta.get(c.domain, 0.0), c.base_difficulty)
        p = model.current_p_know(edge, p0, now)
        if p >= KNOWN_P:
            known.setdefault(c.domain, []).append(p)
    ranked = sorted(
        (d for d, ps in known.items() if len(ps) >= MIN_KNOWN and d != exclude_domain),
        key=lambda d: (-len(known[d]), -fmean(known[d]), DOMAIN_IDS.index(d)),
    )
    return DOMAIN_FRAME.get(ranked[0]) if ranked else None
