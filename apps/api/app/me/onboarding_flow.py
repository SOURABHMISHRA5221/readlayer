"""2-screen onboarding (decisions 41, 42; DESIGN §4, §8, §11.4, §17).

POST /v1/onboarding/resolve   free text → concepts, topics, unrecognised pieces
POST /v1/onboarding/discover  live web results for the chosen topics and concepts
POST /v1/onboarding/pick      "I'd read this" / "Not for me" on a served item
POST /v1/onboarding/know      "Know this?" on a served item's term
POST /v1/onboarding/finish    done; the offered, answered and pick lists are cleared

Signed-in readers after consent only (409 `consent_required` before, demo readers 403).

Privacy rule (absolute): the free text exists only inside one resolve request. It is redacted
and split into pieces; only individual pieces with no exact match reach a model (embedding,
`link_confirm`); nothing of it is stored, logged or sent to search. Search queries are a
taxonomy or concept label from the graph plus a fixed phrase.
"""

import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app import llm
from app.auth import Caller, current_caller
from app.config import Settings, get_settings
from app.content import catalog
from app.content.summary import article_domain
from app.graph.graph import ConceptGraph
from app.graph.loader import get_graph
from app.graph.models import Concept, Domain
from app.graph.resolve import resolve_names
from app.graph.taxonomy import BY_ID
from app.ingest.models import ContentDoc, is_corpus
from app.me.onboarding import consented_user
from app.privacy.redact import redact
from app.reader import onboarding
from app.reader import onboarding_text as ot
from app.reader.events import ConceptRef
from app.recs import feed_rank as fr
from app.recs.feed import concept_spec, item_id, now_utc, topic_specs
from app.recs.feed_router import get_feed_search
from app.recs.models import Format, WebResult
from app.recs.state import DEFAULT_KEY, Served, get_rec_signals
from app.recs.web_search import ONBOARDING_CONCEPT
from app.store.docstore import get_doc_store
from app.store.reader_repo import OnboardingOutcome, ReaderRepo, UserProfile
from app.store.spend_repo import today_utc

log = logging.getLogger("app.me.onboarding_flow")
router = APIRouter()

MAX_TOPICS = 6
MAX_CONCEPTS = 2
CONCEPT_ID = r"^[a-z0-9_]+$"


def _repo() -> ReaderRepo:
    return ReaderRepo(get_doc_store())


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": code, "message": message}, status_code=status)


# ---------------------------------------------------------------- resolve (free text)


class ResolveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=ot.MAX_TEXT_CHARS)


class ConceptOut(BaseModel):
    id: str
    label: str
    domain: Domain


class TopicOut(BaseModel):
    phrase_index: int
    phrase: str  # the redacted piece, echoed to the same client only
    topic: Domain
    via: Literal["alias", "words", "embedding"]


class ResolveOut(BaseModel):
    concepts: list[ConceptOut]
    topics: list[TopicOut]
    unrecognised: list[str]


_topic_vectors: tuple[str, list[list[float]]] | None = None


async def topic_vectors(settings: Settings) -> list[list[float]]:
    """The 14 topics' label + scope embeddings, once per process (and embedding model)."""
    global _topic_vectors
    key = f"{settings.model_embed}|{settings.embed_dim}"
    if _topic_vectors is None or _topic_vectors[0] != key:
        result = await llm.embed(ot.topic_texts(), task_type="SEMANTIC_SIMILARITY")
        _topic_vectors = (key, result.vectors)
    return _topic_vectors[1]


def reset_topic_vectors() -> None:
    global _topic_vectors
    _topic_vectors = None


class _Embedder:
    """Embeds each phrase at most once per request (resolve_names and the topic fallback share
    the vectors) and adds up the cost."""

    def __init__(self) -> None:
        self.vectors: dict[str, list[float]] = {}
        self.cost = 0.0

    async def __call__(self, texts: list[str]) -> list[list[float]]:
        new = list(dict.fromkeys(t for t in texts if t not in self.vectors))
        if new:
            result = await llm.embed(new, task_type="SEMANTIC_SIMILARITY")
            self.cost += result.cost_usd
            self.vectors.update(zip(new, result.vectors, strict=True))
        return [self.vectors[t] for t in texts]


@router.post("/onboarding/resolve", response_model=ResolveOut, responses={429: {}})
async def resolve(
    body: ResolveIn,
    caller: Annotated[Caller, Depends(current_caller)],
    _: Annotated[UserProfile, Depends(consented_user)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ResolveOut | JSONResponse:
    ok = await _repo().reserve_daily("onboarding_resolve_counts", caller.uid, today_utc(),
                                     settings.onboarding_resolve_daily_cap, None, 0)  # fmt: skip
    if not ok:
        return _error(429, "resolve_cap_reached", "That's enough for today. Pick topics instead.")
    graph = get_graph()
    phrases = ot.pieces(redact(body.text))
    concepts: dict[str, Concept] = {}
    topics: list[TopicOut] = []
    misses: list[tuple[int, str]] = []
    for i, piece in enumerate(phrases):
        match = ot.exact_match(graph, piece)
        concepts.update((c.id, c) for c in match.concepts)
        for phrase in match.rest:
            if (topic := ot.alias_topic(phrase)) is not None:
                topics.append(TopicOut(phrase_index=i, phrase=phrase, topic=topic, via="alias"))
            else:
                misses.append((i, phrase))
    # Deterministic before any model call: a phrase whose words match the alias list or a
    # concept label maps to that topic; only the rest reach resolve_names and the embedding.
    worded = _word_topics(graph, misses)
    topics += worded
    matched = {(t.phrase_index, t.phrase) for t in worded}
    pending = [m for m in misses if m not in matched]
    embedder = _Embedder()
    ledger: list[llm.CallMeta] = []
    ids: dict[str, str] = {}
    for _, phrase in pending:
        # One piece per call (privacy rule): resolve_names batches its names into one
        # link_confirm prompt, so the model must never get two of the reader's pieces at once.
        found, _ = await resolve_names(graph, [phrase], settings.link_threshold,
                                       embed=embedder, ledger=ledger)  # fmt: skip
        ids |= found
    if ids:
        for cid in ids.values():
            if (c := graph.get(cid)) is not None:
                concepts[c.id] = c
        resolved = {(i, p) for i, p in pending if p.casefold() in ids}
        pending = [m for m in pending if m not in resolved]
        misses = [m for m in misses if m not in resolved]
    topics += await _topic_fallback(pending, embedder, settings)
    unrecognised = [p for i, p in misses if not any(t.phrase_index == i and t.phrase == p
                                                    for t in topics)]  # fmt: skip
    cost = round(embedder.cost + sum(m.cost_usd for m in ledger), 8)
    log.info("onboarding resolve", extra={"pieces": len(phrases), "concepts": len(concepts),
                                          "topics": len(topics), "unrecognised": len(unrecognised),
                                          "cost_usd": cost})  # fmt: skip
    return ResolveOut(
        concepts=[ConceptOut(id=c.id, label=c.label, domain=c.domain) for c in concepts.values()],
        topics=topics,
        unrecognised=unrecognised,
    )


def _word_topics(graph: ConceptGraph, misses: Sequence[tuple[int, str]]) -> list[TopicOut]:
    """Word-level match (no model call): the phrase's words and 2-word chunks against the alias
    list and concept labels; the strongest match's topic."""
    out = []
    for i, phrase in misses:
        match = ot.word_topic(graph, phrase)
        if match is not None:
            out.append(TopicOut(phrase_index=i, phrase=phrase, topic=match.topic, via="words"))
    return out


async def _topic_fallback(
    misses: Sequence[tuple[int, str]], embedder: _Embedder, settings: Settings
) -> list[TopicOut]:
    """Decision 42: only the redacted phrase is embedded and compared with the topics' scope
    lines; at or above the threshold it maps to the nearest topic. An embedding outage leaves
    the phrases unrecognised."""
    if not misses:
        return []
    try:
        scopes = await topic_vectors(settings)
        vectors = [(await embedder([p]))[0] for _, p in misses]  # one piece per call
    except llm.LLMError:
        return []
    out = []
    for (i, phrase), vec in zip(misses, vectors, strict=True):
        near = ot.nearest_topic(vec, scopes, settings.onboarding_topic_threshold)
        if near is not None:
            out.append(TopicOut(phrase_index=i, phrase=phrase, topic=near[0], via="embedding"))
    return out


# ---------------------------------------------------------------- discover (screen 2)


class DiscoverIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topics: list[Domain] = Field(default_factory=list, max_length=MAX_TOPICS)
    concepts: list[Annotated[str, Field(max_length=120, pattern=CONCEPT_ID)]] = Field(
        default_factory=list, max_length=MAX_CONCEPTS
    )


class KnowTermOut(BaseModel):
    concept_id: str
    label: str
    known: bool | None  # the reader's answer, if any


class DiscoverItemOut(BaseModel):
    id: str
    kind: Literal["web", "library"]
    content_id: str | None
    topic: Domain
    topic_label: str
    format: Format
    title: str
    url: str
    source: str
    snippet: str
    thumbnail: str | None
    duration_or_read_time: int | None
    published_at: str | None
    know: KnowTermOut | None
    liked: bool | None  # the reader's pick, if any


class DiscoverOut(BaseModel):
    items: list[DiscoverItemOut]
    pending: bool  # searches still running: ask again shortly


def _not_done(user: UserProfile) -> None:
    if user.onboarding_done:
        raise HTTPException(status_code=409, detail="onboarding_done")


@router.post("/onboarding/discover", response_model=DiscoverOut)
async def discover(
    body: DiscoverIn,
    caller: Annotated[Caller, Depends(current_caller)],
    user: Annotated[UserProfile, Depends(consented_user)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> DiscoverOut:
    _not_done(user)
    graph, now = get_graph(), now_utc()
    topics = list(dict.fromkeys(body.topics))
    resolved = [graph.get(cid) for cid in dict.fromkeys(body.concepts)]
    if any(c is None for c in resolved):
        raise HTTPException(status_code=422, detail="unknown_concept")
    chosen: list[Concept] = [c for c in resolved if c is not None]
    if not topics and not chosen:
        raise HTTPException(status_code=422, detail="nothing_chosen")
    search = get_feed_search()
    sub_cap = (ONBOARDING_CONCEPT, settings.onboarding_concept_search_daily_cap)
    specs = topic_specs(topics, search.formats, graph, now)
    specs += [concept_spec(c, now, sub_cap) for c in chosen]

    async def may_start() -> bool:
        """Only calls that start new searches count against the reader's daily limit."""
        cap = settings.onboarding_discover_daily_cap
        return await _repo().reserve_daily(
            "onboarding_discover_counts", caller.uid, today_utc(), cap, None, 0
        )

    gathered = await search.gather_specs(specs, graph, now, may_start=may_start)
    stems = [f"feed:{t}" for t in topics] + [f"feed:c:{c.id}" for c in chosen]
    groups = [gathered.by_stem.get(s, []) for s in stems]
    picked = fr.onboarding_mix(groups, now, onboarding.DISCOVER_ITEMS)
    library: dict[str, str] = {}  # url → content id
    if len(picked) < onboarding.DISCOVER_MIN_ITEMS and not gathered.pending:
        domains = list(dict.fromkeys([*topics, *(c.domain for c in chosen)]))
        extra, library = await _library_groups(domains, graph)
        picked = fr.onboarding_mix([[c for c in picked], *extra], now, onboarding.DISCOVER_ITEMS)
    items = await _serve(caller.uid, picked, library, [c.id for c in chosen], graph, now)
    return DiscoverOut(items=items, pending=gathered.pending)


async def _library_groups(
    domains: Sequence[str], graph: ConceptGraph
) -> tuple[list[list[fr.FeedCandidate]], dict[str, str]]:
    """Fallback (cap, failure, thin results): corpus articles in the chosen domains (never a
    page another reader brought in), newest first."""
    docs = [d for d in await catalog.all_docs() if is_corpus(d)]
    by_domain: dict[str, list[ContentDoc]] = {}
    for d in docs:
        dom = article_domain(d, graph)
        if dom in domains:
            by_domain.setdefault(dom, []).append(d)
    urls: dict[str, str] = {}
    groups = []
    for dom in domains:
        newest = sorted(by_domain.get(dom, []), key=lambda d: (d.published or "", d.content_id),
                        reverse=True)[: onboarding.DISCOVER_ITEMS]  # fmt: skip
        group = []
        for d in newest:
            url = d.final_url or d.url
            urls[url] = d.content_id
            result = WebResult(url=url, title=d.title, source=d.site, format="article",
                               snippet=d.description or "", thumbnail=d.image,
                               published_at=d.published)  # fmt: skip
            text = f"{d.title} {d.description or ''}"
            group.append(fr.FeedCandidate(result, dom, fr.named_concepts(graph, text)))
        groups.append(group)
    return groups, urls


def _id(c: fr.FeedCandidate, library: dict[str, str]) -> str:
    cid = library.get(c.result.url)
    return f"lib:{cid}" if cid else item_id(c.result.url)


async def _serve(
    uid: str,
    picked: Sequence[fr.FeedCandidate],
    library: dict[str, str],
    excluded: Sequence[str],
    graph: ConceptGraph,
    now: datetime,
) -> list[DiscoverItemOut]:
    """Remember the items (with their stable Know this? term) and record them as served feed
    items, so picks are rec signals. Items past MAX_OFFERED_ITEMS aren't shown."""
    theta = {d: s.theta for d, s in (await _repo().get_domains(uid)).items()}
    new = [
        (_id(c, library), c.topic, onboarding.term_order(c.concepts, c.topic, theta))
        for c in picked
    ]
    user = await _repo().offer_onboarding(
        uid, lambda offered: onboarding.offer(offered, new, excluded)
    )
    shown = [c for c in picked if _id(c, library) in user.onboarding_offered]
    if shown:
        served = {_id(c, library): Served(c.result.format, "feed") for c in shown}
        await get_rec_signals().remember_served(uid, DEFAULT_KEY, served, now)
    return [_item_out(c, library, user, graph) for c in shown]


def _item_out(
    c: fr.FeedCandidate, library: dict[str, str], user: UserProfile, graph: ConceptGraph
) -> DiscoverItemOut:
    iid, res = _id(c, library), c.result
    offered = user.onboarding_offered[iid]
    term = graph.get(offered["concept"]) if offered.get("concept") else None
    pick = user.onboarding_picks.get(iid)
    return DiscoverItemOut(
        id=iid,
        kind="library" if iid.startswith("lib:") else "web",
        content_id=library.get(res.url),
        topic=c.topic,  # type: ignore[arg-type]
        topic_label=BY_ID[c.topic].label,
        format=res.format,
        title=res.title,
        url=res.url,
        source=res.source,
        snippet=res.snippet,
        thumbnail=res.thumbnail,
        duration_or_read_time=res.duration_or_read_time,
        published_at=res.published_at,
        know=_term_out(term, user),
        liked=pick["liked"] if pick else None,
    )


def _term_out(term: Concept | None, user: UserProfile) -> KnowTermOut | None:
    if term is None:
        return None
    known = user.onboarding_answered.get(term.id)
    return KnowTermOut(concept_id=term.id, label=term.label, known=known)


# ---------------------------------------------------------------- pick, know, finish


class PickIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_id: str = Field(max_length=80)
    liked: bool


class KnowIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    concept_id: str = Field(max_length=120, pattern=CONCEPT_ID)
    known: bool


_REFUSED: dict[OnboardingOutcome, tuple[int, str]] = {
    "done": (409, "onboarding_done"),
    "unknown": (404, "not_offered"),
    "repeat": (409, "already_answered"),
    "limit": (409, "too_many_answers"),
}


def _refuse(outcome: OnboardingOutcome) -> JSONResponse:
    status, code = _REFUSED[outcome]
    return JSONResponse({"error": code}, status_code=status)


@router.post("/onboarding/pick", response_model=None)
async def pick(
    body: PickIn,
    caller: Annotated[Caller, Depends(current_caller)],
    _: Annotated[UserProfile, Depends(consented_user)],
) -> dict[str, Any] | JSONResponse:
    """The topic comes from the served item, never from the client."""
    outcome = await _repo().onboarding_pick(
        caller.uid, body.item_id, body.liked, onboarding.MAX_PICKS,
        lambda interest: onboarding.with_pick(interest, body.liked),
    )  # fmt: skip
    if outcome != "ok":
        return _refuse(outcome)
    kind = "rec_clicked" if body.liked else "rec_dismissed"
    await get_rec_signals().apply(
        caller.uid, DEFAULT_KEY, [(f"onboarding-pick:{body.item_id}", kind, body.item_id)]
    )
    return {"saved": True}


@router.post("/onboarding/know", response_model=None)
async def know(
    body: KnowIn,
    caller: Annotated[Caller, Depends(current_caller)],
    _: Annotated[UserProfile, Depends(consented_user)],
) -> dict[str, Any] | JSONResponse:
    concept = get_graph().get(body.concept_id)
    if concept is None:
        return _refuse("unknown")
    now = datetime.now(UTC)

    def apply(edge, theta):  # type: ignore[no-untyped-def]
        out = onboarding.apply_answer(concept, edge, theta, onboarding.KNOW_ANSWER[body.known], now)
        return out.edge, out.theta

    outcome = await _repo().onboarding_know(
        caller.uid, concept.id, body.known, ConceptRef(concept.domain, concept.base_difficulty),
        apply, onboarding.MAX_KNOW_ANSWERS,
    )  # fmt: skip
    if outcome != "ok":
        return _refuse(outcome)
    return {"saved": True}


@router.post("/onboarding/finish")
async def finish(
    caller: Annotated[Caller, Depends(current_caller)],
    user: Annotated[UserProfile, Depends(consented_user)],
) -> dict[str, Literal[True]]:
    if user.field is None:  # screen 1 not saved yet: nothing to finish
        raise HTTPException(status_code=409, detail="onboarding_incomplete")
    await _repo().finish_onboarding(caller.uid)
    return {"done": True}
