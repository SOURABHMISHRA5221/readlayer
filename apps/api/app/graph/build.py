"""Pure helpers for building the concept graph (DESIGN §2). No I/O, no SDK calls.

scripts/build_concepts.py does the orchestration (Firestore, LLM, Wikipedia); everything here
is deterministic and unit-tested.
"""

import math
import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import networkx as nx
import numpy as np

# ---------------------------------------------------------------- labels and ids

_PAREN = re.compile(r"\s*\([^)]*\)")
_NON_WORD = re.compile(r"[^\w\s&%]")
_SPACE = re.compile(r"\s+")
_NO_FOLD = ("ss", "us", "is", "ics", "news")


def normalize_label(text: str) -> str:
    """Grouping key: casefold, drop parentheticals and punctuation, fold a trailing plural."""
    t = _PAREN.sub("", text.casefold().replace("’", "'"))
    t = t.replace("-", " ").replace("–", " ").replace("'s ", " ").replace("'", "")
    t = _SPACE.sub(" ", _NON_WORD.sub(" ", t)).strip()
    if not t:
        return t
    head, _, last = t.rpartition(" ")
    if len(last) > 3 and not last.endswith(_NO_FOLD):
        if last.endswith("ies"):
            last = last[:-3] + "y"
        elif last.endswith("s"):
            last = last[:-1]
    return f"{head} {last}".strip()


def slug_ids(labels: Sequence[str], max_len: int = 48) -> list[str]:
    """`c_<snake>` ids, unique within the list (collisions get _2, _3, ...)."""
    ids: list[str] = []
    used: set[str] = set()
    for label in labels:
        ascii_label = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode()
        base = re.sub(r"[^a-z0-9]+", "_", ascii_label.lower()).strip("_")[:max_len].strip("_")
        base = f"c_{base or 'concept'}"
        cid, n = base, 2
        while cid in used:
            cid, n = f"{base}_{n}", n + 1
        used.add(cid)
        ids.append(cid)
    return ids


# ---------------------------------------------------------------- clustering


def clusters(n: int, pairs: Iterable[tuple[int, int]]) -> list[list[int]]:
    """Connected components over accepted pairs (union-find); singletons included."""
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in pairs:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def candidate_pairs(
    vectors: np.ndarray, low: float, high: float = math.inf, top_k: int = 5
) -> list[tuple[int, int, float]]:
    """Pairs (i < j) with low <= cosine < high, taking each row's `top_k` nearest in that band.

    Rows must be L2-normalised. The per-row cap bounds LLM merge checks in dense regions.
    """
    sims = vectors @ vectors.T
    np.fill_diagonal(sims, -np.inf)
    found: dict[tuple[int, int], float] = {}
    for i, row in enumerate(sims):
        idx = np.flatnonzero((row >= low) & (row < high))
        for j in idx[np.argsort(-row[idx])][:top_k]:
            found[(min(i, int(j)), max(i, int(j)))] = float(row[j])
    return [(i, j, s) for (i, j), s in sorted(found.items())]


# ---------------------------------------------------------------- near-duplicate documents


def shingles(text: str, k: int = 5) -> set[str]:
    words = re.findall(r"\w+", text.casefold())
    return (
        {" ".join(words[i : i + k]) for i in range(max(len(words) - k + 1, 1))} if words else set()
    )


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


@dataclass(frozen=True)
class DuplicatePair:
    a: int
    b: int
    cosine: float
    jaccard: float


def duplicate_pairs(
    shingle_sets: Sequence[set[str]],
    vectors: np.ndarray,
    *,
    cosine_min: float = 0.92,
    jaccard_min: float = 0.5,
    jaccard_confirm: float = 0.15,
) -> list[DuplicatePair]:
    """Syndicated or near-identical docs: heavy text overlap, or near-identical title+lead
    embeddings confirmed by some text overlap (so same-topic, different stories don't merge).
    """
    sims = vectors @ vectors.T
    out = []
    for i in range(len(shingle_sets)):
        for j in range(i + 1, len(shingle_sets)):
            jac = jaccard(shingle_sets[i], shingle_sets[j])
            cos = float(sims[i, j])
            if jac >= jaccard_min or (cos >= cosine_min and jac >= jaccard_confirm):
                out.append(DuplicatePair(i, j, cos, jac))
    return out


# ---------------------------------------------------------------- concept attributes

KEEP_KINDS = frozenset(
    {
        "idea",
        "jargon",
        "institution",
        "regulator",
        "committee",
        "index",
        "tax",
        "policy",
        "scheme",
        "instrument",
        "entity_type",
        "market_event",
        "unit",
    }
)
DROP_KINDS = frozenset({"company", "person", "place", "event", "generic"})
KINDS = KEEP_KINDS | DROP_KINDS

MIN_DOC_GROUPS = 2
SINGLE_DOC_MIN_SPEC = 2


def apply_keep(
    kind: str,
    is_seed: bool = False,
    doc_groups: int = MIN_DOC_GROUPS,
    specialization: int = 5,
) -> bool:
    """Keep ideas, jargon, instruments, types of firm, market phenomena, units and named
    institutions/indices/taxes/policies/schemes; drop companies, people, places, one-off events
    and everyday words. A concept seen in fewer than MIN_DOC_GROUPS duplicate groups also needs
    specialization ≥ SINGLE_DOC_MIN_SPEC. Wikipedia seed concepts always stay.
    """
    if is_seed:
        return True
    if kind not in KEEP_KINDS:
        return False
    return doc_groups >= MIN_DOC_GROUPS or specialization >= SINGLE_DOC_MIN_SPEC


def difficulty(specialization: int, zipf: float) -> float:
    """DESIGN §2: LLM 1–5 mapped to −2..2, blended with word frequency (rare = harder)."""
    llm_b = float(min(max(specialization, 1), 5) - 3)
    freq_b = min(max(4.0 - zipf, -2.0), 2.0)
    return round(min(max(0.75 * llm_b + 0.25 * freq_b, -2.0), 2.0), 3)


# ---------------------------------------------------------------- prerequisites


@dataclass(frozen=True)
class Prereq:
    id: str
    confidence: float


MAX_PREREQS = 3


def validate_prereqs(
    concept_id: str, proposed: Iterable[Prereq], allowed: set[str]
) -> list[Prereq]:
    """Existing ids only, never self, no repeats, at most 3 (highest confidence first)."""
    seen: set[str] = set()
    kept = []
    for p in sorted(proposed, key=lambda p: -p.confidence):
        if p.id == concept_id or p.id not in allowed or p.id in seen:
            continue
        seen.add(p.id)
        kept.append(p)
    return kept[:MAX_PREREQS]


def prereq_digraph(edges: dict[str, list[Prereq]]) -> nx.DiGraph:
    """Edge prerequisite → concept."""
    g = nx.DiGraph()
    g.add_nodes_from(edges)
    for child, prereqs in edges.items():
        for p in prereqs:
            g.add_edge(p.id, child, confidence=p.confidence)
    return g


def break_cycles(
    edges: dict[str, list[Prereq]], base_difficulty: dict[str, float]
) -> tuple[dict[str, list[Prereq]], list[tuple[str, str]]]:
    """Remove edges until the prerequisite graph is a DAG.

    In each cycle drop the least confident edge; on a tie, the one whose prerequisite is harder
    than its dependent. Returns new edges and the removed (prereq, concept) pairs.
    """
    g = prereq_digraph(edges)
    removed: list[tuple[str, str]] = []
    while True:
        try:
            cycle = nx.find_cycle(g)
        except nx.NetworkXNoCycle:
            break
        u, v = min(
            ((u, v) for u, v, *_ in cycle),
            key=lambda e: (
                g.edges[e]["confidence"],
                -(base_difficulty.get(e[0], 0.0) - base_difficulty.get(e[1], 0.0)),
            ),
        )
        g.remove_edge(u, v)
        removed.append((u, v))
    dropped = set(removed)
    clean = {c: [p for p in ps if (p.id, c) not in dropped] for c, ps in edges.items()}
    return clean, removed


# ---------------------------------------------------------------- threshold calibration

PERCENTILES = (5, 10, 25, 50, 75, 90, 95)


def percentiles(scores: Sequence[float]) -> dict[int, float]:
    if not scores:
        return {}
    return {p: round(float(np.percentile(scores, p)), 4) for p in PERCENTILES}


def calibrate_threshold(
    positives: Sequence[float], negatives: Sequence[float], min_precision: float = 0.95
) -> float | None:
    """Lowest threshold t where precision of `score >= t` is at least `min_precision`.

    None when no threshold reaches it. Returned value is floored to 4 decimals, which can only
    admit scores equal to the chosen point.
    """
    pos = np.sort(np.asarray(positives, dtype=float))
    neg = np.sort(np.asarray(negatives, dtype=float))
    for t in np.unique(np.concatenate([pos, neg])):
        tp = len(pos) - np.searchsorted(pos, t, side="left")
        fp = len(neg) - np.searchsorted(neg, t, side="left")
        if tp > 0 and tp / (tp + fp) >= min_precision:
            return math.floor(float(t) * 10_000) / 10_000
    return None
