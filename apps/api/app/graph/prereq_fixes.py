"""Prerequisite edges judged wrong, dropped where the API builds its graph (M9 part 2, S2).

Stored edges carry no confidence and some live in `concepts.json` too, so instead of rewriting
production data before the freeze, the API drops these (concept id, prerequisite id) pairs when it
loads the graph file and when it merges concepts grown elsewhere. Each was judged wrong in
`docs/plans/M9.md` (part 2 evidence) or `apps/api/evals/prereq_verdicts.json`: lexical collisions
across domains, mostly. A re-fold after the hackathon should drop them from the data itself.
"""

from collections.abc import Sequence

from app.graph.models import Concept

KNOWN_WRONG_PREREQS: frozenset[tuple[str, str]] = frozenset({
    ("c_pfos", "c_phosita"),  # a patent-law term
    ("c_seizure_memo", "c_seizure"),  # the medical sense, not the legal one
    ("c_humanoid_robot", "c_mechanism"),
    ("c_superforecaster", "c_macroeconomic_forecasting"),  # borderline counts as wrong
    ("c_education_minister", "c_administration"),  # a generic business concept
    ("c_c2_photorespiratory_carbon_pump", "c_carbon_cycle"),
    ("c_franchise_t20_leagues", "c_franchise"),  # a business franchise
    ("c_wearable_technology", "c_human_body"),
})  # fmt: skip


def without_known_wrong(concepts: Sequence[Concept]) -> list[Concept]:
    """The concepts with any listed edge removed (copy-on-write: unchanged concepts are reused)."""
    out: list[Concept] = []
    for c in concepts:
        kept = [p for p in c.prerequisites if (c.id, p) not in KNOWN_WRONG_PREREQS]
        out.append(
            c if len(kept) == len(c.prerequisites) else c.model_copy(update={"prerequisites": kept})
        )
    return out
