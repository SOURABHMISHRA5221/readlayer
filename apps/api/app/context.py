"""Who is reading, as the scorers and recommenders see it.

Anonymous (demo) readers carry a persona (`?persona=`, default newcomer). Each persona is a
seeded reader graph: the read-only template until the reader's first event, then their own copy
at `users/{uid}/demo_graphs/{persona}`, so one demo session can switch personas and each one
learns separately. Signed-in readers are themselves: their own graph, neutral (θ = 0, no
edges) until they read, no persona.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Query

from app.auth import Caller, current_caller
from app.reader.state import Density, PersonaKey, ReaderState
from app.recs.state import DEFAULT_KEY
from app.store.docstore import get_doc_store
from app.store.reader_repo import DomainState, ReaderRepo, UserProfile

DEMO_DEFAULT: PersonaKey = "newcomer"


@dataclass(frozen=True)
class ReaderContext:
    caller: Caller
    persona: PersonaKey | None
    state: ReaderState
    user: UserProfile
    domains: Mapping[str, DomainState]

    @property
    def uid(self) -> str:
        return self.caller.uid

    @property
    def theta(self) -> Mapping[str, float]:
        return self.state.theta

    @property
    def density(self) -> Density:
        return self.user.density

    @property
    def rec_key(self) -> str:
        """Which rec_signals document this reader's Up next signals live in."""
        return self.persona or DEFAULT_KEY

    @property
    def view_key(self) -> str:
        """Cache key for derived per-reader views (library rows): equal keys, equal output."""
        return self.state.rev


def scope_persona(caller: Caller, persona: PersonaKey | None) -> PersonaKey | None:
    """Personas are for demo (anonymous) readers only; signed-in readers are themselves."""
    return (persona or DEMO_DEFAULT) if caller.is_anonymous else None


async def reader_context(
    caller: Annotated[Caller, Depends(current_caller)],
    persona: Annotated[PersonaKey | None, Query()] = None,
) -> ReaderContext:
    scope = scope_persona(caller, persona)
    state, user, domains = await ReaderRepo(get_doc_store()).load_state(caller.uid, scope)
    return ReaderContext(caller, scope, state, user, domains)
