"""Who is reading, as the scorers and recommenders see it.

Anonymous (demo) readers carry a persona (`?persona=`, default newcomer). Each persona is a
seeded reader graph: the read-only template until the reader's first event, then their own copy
at `users/{uid}/demo_graphs/{persona}`, so one demo session can switch personas and each one
learns separately. Signed-in readers are themselves: their own graph, neutral (θ = 0, no
edges) until they read, no persona.
"""

import asyncio
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Query

from app.auth import Caller, current_caller
from app.ingest.models import is_corpus
from app.reader.state import Density, PersonaKey, ReaderState
from app.recs.state import DEFAULT_KEY
from app.store.docstore import get_doc_store
from app.store.reader_repo import DomainState, ReaderRepo, UserProfile

if TYPE_CHECKING:
    from app.ingest.models import ContentDoc

DEMO_DEFAULT: PersonaKey = "newcomer"


@dataclass(frozen=True)
class ReaderContext:
    caller: Caller
    persona: PersonaKey | None
    state: ReaderState
    user: UserProfile
    domains: Mapping[str, DomainState]
    # Pages this reader brought in (M7.5): the only NOT_CORPUS docs their library and Up next
    # list. Read once per request.
    ingested: frozenset[str] = frozenset()

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
    repo = ReaderRepo(get_doc_store())
    (state, user, domains), ingested = await asyncio.gather(
        repo.load_state(caller.uid, scope), repo.ingested_ids(caller.uid)
    )
    return ReaderContext(caller, scope, state, user, domains, ingested)


def hidden_ids(docs: Iterable["ContentDoc"], ctx: ReaderContext) -> frozenset[str]:
    """Reader-brought pages (NOT_CORPUS) this reader didn't bring in: filtered per request,
    after any shared cache, never part of a cache key."""
    return frozenset(
        d.content_id for d in docs if not is_corpus(d) and d.content_id not in ctx.ingested
    )
