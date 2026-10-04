"""Who is reading, as the scorers and recommenders see it.

Anonymous (demo) readers carry a persona (`?persona=`, default newcomer) whose hand-set θ is
fixed until M4 replaces personas with seeded reader graphs. Signed-in readers are themselves:
θ per domain from `users/{uid}/domains` (0 where nothing is known yet), no persona.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Query

from app.auth import Caller, current_caller
from app.recs.state import DEFAULT_KEY
from app.scoring.placeholder import PERSONAS, PersonaKey
from app.store.docstore import get_doc_store
from app.store.reader_repo import ReaderRepo

DEMO_DEFAULT: PersonaKey = "newcomer"


@dataclass(frozen=True)
class ReaderContext:
    caller: Caller
    persona: PersonaKey | None
    theta: Mapping[str, float]
    theta_fixed: bool

    @property
    def uid(self) -> str:
        return self.caller.uid

    @property
    def rec_key(self) -> str:
        """Which rec_signals document this reader's Up next signals live in."""
        return self.persona or DEFAULT_KEY

    @property
    def view_key(self) -> str:
        """Cache key for derived per-reader views (library rows): equal keys, equal output."""
        if self.persona:
            return f"persona:{self.persona}"
        return "theta:" + ",".join(f"{d}={t:.6f}" for d, t in sorted(self.theta.items()))


async def reader_context(
    caller: Annotated[Caller, Depends(current_caller)],
    persona: Annotated[PersonaKey | None, Query()] = None,
) -> ReaderContext:
    if caller.is_anonymous:
        key = persona or DEMO_DEFAULT
        return ReaderContext(caller, key, PERSONAS[key].theta, theta_fixed=True)
    domains = await ReaderRepo(get_doc_store()).get_domains(caller.uid)
    return ReaderContext(caller, None, {d: s.theta for d, s in domains.items()}, False)
