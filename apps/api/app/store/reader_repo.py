"""Per-reader Firestore layout (DESIGN §4) — the only module that reads or writes `users/{uid}`
apart from the rec-signal repository (app/recs/state.py), which shares USER_SUBCOLLECTIONS.

users/{uid}                    profile and settings (no email, no name)
users/{uid}/domains/{domain}   theta, thinks_in, interest
users/{uid}/knows/{concept}    Beta edge + evidence + band fields
users/{uid}/events/{event_id}  raw events, `expire_at` drives the 90-day Firestore TTL
users/{uid}/weekly/{iso_week}  words_read, annotations_shown, content_ids (dedupe)
users/{uid}/profile_edits/{id} M7
users/{uid}/rec_signals/{key}  app/recs/state.py
users/{uid}/ingest_counts/{d}  new URLs ingested that UTC day
users/{uid}/explain_counts/{d} explanations generated (not cached) that UTC day
users/{uid}/demo_graphs/{p}    a demo reader's graph for persona p: θ, threshold_offset, knows
                               map, engaged contents. Copied from persona_templates/{p} on the
                               first event or correction; until then the template is read as-is.

Export and delete both walk USER_SUBCOLLECTIONS; a test fails if anything is written under
`users/{uid}` outside it.
"""

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.reader import events as reader_events
from app.reader.events import ConceptRef, EventOutcome, ReaderEvent
from app.reader.model import Edge, Evidence
from app.reader.profile import iso_week
from app.reader.state import ExplanationStyle, PersonaKey, ReaderState, touch_engaged
from app.scoring.rules import next_offset
from app.store.docstore import Doc, DocStore, Txn

USER_SUBCOLLECTIONS = (
    "domains",
    "knows",
    "events",
    "weekly",
    "profile_edits",
    "rec_signals",
    "ingest_counts",
    "demo_graphs",
    "explain_counts",
    "profile_edit_counts",
)
EVENT_TTL = timedelta(days=90)
MAX_WEEKLY_CONTENT_IDS = 500
# Demo graphs live in one document (Firestore limit 1 MiB): fewer evidence entries per edge,
# and the oldest low-confidence non-seed edges are dropped past MAX_DEMO_DOC_BYTES.
DEMO_MAX_EVIDENCE = 5
MAX_DEMO_DOC_BYTES = 800_000
FIRESTORE_DOC_LIMIT = 1_048_576

Density = Literal["minimal", "balanced", "guided"]


class UserProfile(BaseModel):
    """users/{uid}. Settings the reader controls plus bookkeeping; never an email or name."""

    is_anonymous: bool = False
    created_at: datetime | None = None
    onboarding_done: bool = False
    density: Density = "balanced"
    threshold_offset: float = 0.0
    prompts_today: int = 0
    learning_paused: bool = False
    explanation_style: ExplanationStyle = "normal"
    thinks_in: list[str] = Field(default_factory=list)
    # M7: consent (version + time; DESIGN §11.4), onboarding answers and calibration progress.
    # Nothing about a signed-in reader is recorded before `consent` is set.
    consent: dict[str, Any] | None = None
    field: str | None = None
    onboarding: dict[str, Any] = Field(default_factory=dict)  # interests, comfort, liked ids
    calibration: dict[str, Any] = Field(default_factory=lambda: {"asked": [], "answers": 0})
    # Scoring state (DESIGN §5–6). Demo readers keep offset and engaged per persona instead.
    engaged: dict[str, datetime] = Field(default_factory=dict)  # content_id → last engaged
    prompts: dict[str, list[str]] = Field(default_factory=dict)  # UTC day → prompted contents
    rev: int = 0  # bumped on every change to the reader's graph; derived caches key on it

    @property
    def may_record(self) -> bool:
        """Demo readers agree by starting the demo; signed-in readers on the consent screen."""
        return self.is_anonymous or self.consent is not None


@dataclass(frozen=True)
class DomainState:
    theta: float = 0.0
    thinks_in: float = 0.0
    interest: float = 0.0


def user_path(uid: str) -> str:
    if not uid or "/" in uid:
        raise ValueError("invalid uid")
    return f"users/{uid}"


def sub_path(uid: str, collection: str, doc_id: str) -> str:
    if collection not in USER_SUBCOLLECTIONS:
        raise ValueError(f"{collection} is not a registered user subcollection")
    if not doc_id or "/" in doc_id:
        raise ValueError("invalid document id")
    return f"{user_path(uid)}/{collection}/{doc_id}"


# ---------------------------------------------------------------- (de)serialisation


def edge_to_doc(edge: Edge, domain: str) -> Doc:
    return {
        "alpha": edge.alpha,
        "beta": edge.beta,
        "last_seen": edge.last_seen,
        "band": edge.band,
        "band_prev": edge.band_prev,
        "band_changed_at": edge.band_changed_at,
        "evidence": [{"type": e.type, "w": e.w, "at": e.at} for e in edge.evidence],
        "domain": domain,
    }


def edge_from_doc(doc: Doc) -> Edge:
    return Edge(
        alpha=float(doc["alpha"]),
        beta=float(doc["beta"]),
        last_seen=doc["last_seen"],
        band=doc["band"],
        evidence=tuple(
            Evidence(e["type"], float(e["w"]), e["at"]) for e in doc.get("evidence", [])
        ),
        band_prev=doc.get("band_prev"),
        band_changed_at=doc.get("band_changed_at"),
    )


def _domain_from_doc(doc: Doc | None) -> DomainState:
    doc = doc or {}
    return DomainState(
        float(doc.get("theta", 0.0)),
        float(doc.get("thinks_in", 0.0)),
        float(doc.get("interest", 0.0)),
    )


def _event_doc(ev: ReaderEvent, now: datetime) -> Doc:
    return {
        "type": ev.type,
        "at": ev.at,
        "received_at": now,
        "expire_at": now + EVENT_TTL,
        "concept_id": ev.concept_id,
        "content_id": ev.content_id,
        "paragraph_id": ev.paragraph_id,
        "words": ev.words,
        "ms": ev.ms,
    }


def firestore_size(value: Any) -> int:
    """Firestore's storage size rules (strings len+1, numbers/timestamps 8, maps sum key+value),
    close enough to keep a document clear of the 1 MiB limit."""
    if value is None or isinstance(value, bool):
        return 1
    if isinstance(value, str):
        return len(value.encode()) + 1
    if isinstance(value, int | float | datetime):
        return 8
    if isinstance(value, list | tuple):
        return sum(firestore_size(v) for v in value)
    if isinstance(value, dict):
        return sum(len(str(k).encode()) + 1 + firestore_size(v) for k, v in value.items())
    return len(str(value).encode()) + 1


def fit_demo_doc(
    doc: Doc, path: str, keep: set[str], limit: int = MAX_DEMO_DOC_BYTES
) -> tuple[Doc, int]:
    """Drop the oldest low-confidence non-seed edges (never ones in `keep`) until the document
    fits. Returns the document and how many edges were dropped."""
    size = len(path.encode()) + 16 + firestore_size(doc)
    if size <= limit:
        return doc, 0
    knows = dict(doc["knows"])
    victims = sorted(
        (
            (float(e["alpha"]) + float(e["beta"]), e["last_seen"], cid)
            for cid, e in knows.items()
            if not e.get("seeded") and cid not in keep
        ),
    )
    dropped = 0
    for _, _, cid in victims:
        if size <= limit:
            break
        size -= len(cid.encode()) + 1 + firestore_size(knows.pop(cid))
        dropped += 1
    return doc | {"knows": knows}, dropped


def demo_path(uid: str, persona: PersonaKey) -> str:
    return sub_path(uid, "demo_graphs", persona)


def _theta_map(doc: Mapping[str, Any] | None) -> dict[str, float]:
    return {d: float(t) for d, t in ((doc or {}).get("theta") or {}).items()}


def state_from_demo(uid: str, persona: PersonaKey, doc: Doc, copied: bool) -> ReaderState:
    rev = f"demo:{uid}:{persona}:{doc.get('rev', 0)}" if copied else f"template:{doc['version']}"
    return ReaderState(
        theta=_theta_map(doc),
        edges={cid: edge_from_doc(e) for cid, e in (doc.get("knows") or {}).items()},
        threshold_offset=float(doc.get("threshold_offset", 0.0)),
        engaged=dict(doc.get("engaged") or {}),
        thinks_in=tuple(doc.get("thinks_in") or ()),
        rev=rev,
    )


def state_from_user(
    uid: str, user: UserProfile, domains: Mapping[str, "DomainState"], knows: Mapping[str, Edge]
) -> ReaderState:
    return ReaderState(
        theta={d: s.theta for d, s in domains.items()},
        edges=dict(knows),
        threshold_offset=user.threshold_offset,
        engaged=dict(user.engaged),
        rev=f"user:{uid}:{user.rev}",
    )


def _copy_template(template: Doc, now: datetime) -> Doc:
    """A demo reader's own graph, started from the persona template."""
    return {
        "persona": template["persona"],
        "template_version": template["version"],
        "theta": dict(template.get("theta") or {}),
        "threshold_offset": float(template.get("threshold_offset", 0.0)),
        "knows": dict(template.get("knows") or {}),
        "engaged": {},
        "rev": 0,
        "created_at": now,
    }


@dataclass(frozen=True)
class EventsResult:
    applied: int
    ignored: int
    paused: bool
    consent_required: bool = False


class ReaderRepo:
    def __init__(self, store: DocStore) -> None:
        self._store = store

    # ------------------------------------------------------------ profile and settings

    async def ensure_user(self, uid: str, is_anonymous: bool, now: datetime) -> None:
        async def body(t: Txn) -> None:
            if await t.get(user_path(uid)) is None:
                profile = UserProfile(is_anonymous=is_anonymous, created_at=now)
                t.set(user_path(uid), profile.model_dump())

        await self._store.run(body)

    async def get_user(self, uid: str) -> UserProfile:
        return UserProfile.model_validate(await self._store.get(user_path(uid)) or {})

    async def update_settings(self, uid: str, changes: Mapping[str, Any]) -> UserProfile:
        async def body(t: Txn) -> UserProfile:
            current = UserProfile.model_validate(await t.get(user_path(uid)) or {})
            updated = UserProfile.model_validate(current.model_dump() | dict(changes))
            t.set(user_path(uid), updated.model_dump())
            return updated

        return await self._store.run(body)

    async def get_domains(self, uid: str) -> dict[str, DomainState]:
        rows = await self._store.list(f"{user_path(uid)}/domains")
        return {d: _domain_from_doc(doc) for d, doc in rows}

    async def get_knows(self, uid: str) -> dict[str, Edge]:
        rows = await self._store.list(f"{user_path(uid)}/knows")
        return {cid: edge_from_doc(doc) for cid, doc in rows}

    async def get_weekly(self, uid: str) -> dict[str, Doc]:
        return dict(await self._store.list(f"{user_path(uid)}/weekly"))

    async def _template(self, persona: PersonaKey) -> Doc:
        from app.store.persona_repo import get_template

        return await get_template(self._store, persona)

    async def load_state(
        self, uid: str, persona: PersonaKey | None
    ) -> tuple[ReaderState, UserProfile, dict[str, DomainState]]:
        """The reader's scoring state: their own graph, or for a demo reader the persona's
        copy (the template itself until their first event). Reads only; nothing is written."""
        if persona is not None:
            user_doc, demo = await asyncio.gather(
                self._store.get(user_path(uid)), self._store.get(demo_path(uid, persona))
            )
            user = UserProfile.model_validate(user_doc or {})
            copied = demo is not None
            doc = demo if demo is not None else await self._template(persona)
            state = state_from_demo(uid, persona, doc, copied)
            domains = {d: DomainState(theta=t) for d, t in state.theta.items()}
            return state, user, domains
        user_doc, domains, knows = await asyncio.gather(
            self._store.get(user_path(uid)), self.get_domains(uid), self.get_knows(uid)
        )
        user = UserProfile.model_validate(user_doc or {})
        return state_from_user(uid, user, domains, knows), user, domains

    # ------------------------------------------------------------ events and corrections

    async def apply_events(
        self,
        uid: str,
        persona: PersonaKey | None,
        events: list[ReaderEvent],
        refs: Mapping[str, ConceptRef],
        now: datetime,
    ) -> EventsResult:
        """One transaction: pause check, idempotency, KNOWS + θ + threshold_offset + engaged +
        weekly updates, event log. A demo reader's first event copies the persona template."""
        template = await self._template(persona) if persona is not None else None

        async def body(t: Txn) -> EventsResult:
            user_doc = await t.get(user_path(uid))
            user = UserProfile.model_validate(user_doc or {})
            if not user.may_record:
                return EventsResult(0, len(events), False, consent_required=True)
            if user.learning_paused:
                return EventsResult(0, len(events), True)
            stored = await t.get_all([sub_path(uid, "events", e.id) for e in events])
            fresh = [e for e in events if stored[sub_path(uid, "events", e.id)] is None]
            cids = sorted({e.concept_id for e in fresh if e.concept_id in refs})
            week = iso_week(now)
            weekly = (await t.get(sub_path(uid, "weekly", week))) or {}
            if persona is not None and template is not None:
                out = await self._demo_events(t, uid, persona, template, fresh, cids, refs, now)
            else:
                out = await self._user_events(t, uid, user, fresh, cids, refs, now)
            if out.words_read:
                weekly["words_read"] = int(weekly.get("words_read", 0)) + out.words_read
                t.set(sub_path(uid, "weekly", week), weekly)
            applied = set(out.applied)
            for e in fresh:
                if e.id in applied:
                    t.set(sub_path(uid, "events", e.id), _event_doc(e, now))
            return EventsResult(len(out.applied), len(events) - len(out.applied), False)

        return await self._store.run(body)

    async def _user_events(
        self,
        t: Txn,
        uid: str,
        user: UserProfile,
        fresh: list[ReaderEvent],
        cids: list[str],
        refs: Mapping[str, ConceptRef],
        now: datetime,
    ) -> EventOutcome:
        domains = sorted({refs[c].domain for c in cids})
        reads = await t.get_all(
            [sub_path(uid, "knows", c) for c in cids]
            + [sub_path(uid, "domains", d) for d in domains]
        )
        edges = {
            c: edge_from_doc(doc)
            for c in cids
            if (doc := reads[sub_path(uid, "knows", c)]) is not None
        }
        stored_domains = {d: reads[sub_path(uid, "domains", d)] for d in domains}
        theta = {
            d: float(doc["theta"]) for d, doc in stored_domains.items() if doc and "theta" in doc
        }
        out = reader_events.apply_events(fresh, edges, theta, refs, now)
        for cid, edge in out.edges.items():
            t.set(sub_path(uid, "knows", cid), edge_to_doc(edge, refs[cid].domain))
        for d, th in out.theta.items():
            t.set(sub_path(uid, "domains", d), (stored_domains.get(d) or {}) | {"theta": th})
        if out.applied:
            updated = user.model_copy(
                update={
                    "threshold_offset": next_offset(user.threshold_offset, out.applied_types),
                    "engaged": touch_engaged(user.engaged, set(out.content_ids), now),
                    "rev": user.rev + 1,
                }
            )
            t.set(user_path(uid), updated.model_dump())
        return out

    async def _demo_events(
        self,
        t: Txn,
        uid: str,
        persona: PersonaKey,
        template: Doc,
        fresh: list[ReaderEvent],
        cids: list[str],
        refs: Mapping[str, ConceptRef],
        now: datetime,
    ) -> EventOutcome:
        path = demo_path(uid, persona)
        doc = (await t.get(path)) or _copy_template(template, now)
        knows = doc.get("knows") or {}
        edges = {c: edge_from_doc(knows[c]) for c in cids if c in knows}
        out = reader_events.apply_events(fresh, edges, _theta_map(doc), refs, now)
        if not out.applied:
            return out
        new_knows = dict(knows)
        for cid, edge in out.edges.items():
            trimmed = Edge(**(vars(edge) | {"evidence": edge.evidence[-DEMO_MAX_EVIDENCE:]}))
            seeded = bool(knows.get(cid, {}).get("seeded"))
            new_knows[cid] = edge_to_doc(trimmed, refs[cid].domain) | {"seeded": seeded}
        updated = doc | {
            "knows": new_knows,
            "theta": _theta_map(doc) | out.theta,
            "threshold_offset": next_offset(
                float(doc.get("threshold_offset", 0.0)), out.applied_types
            ),
            "engaged": touch_engaged(doc.get("engaged") or {}, set(out.content_ids), now),
            "rev": int(doc.get("rev", 0)) + 1,
            "updated_at": now,
        }
        fitted, _ = fit_demo_doc(updated, path, keep=set(out.edges))
        t.set(path, fitted)
        return out

    async def correct(
        self,
        uid: str,
        persona: PersonaKey | None,
        concept_id: str,
        ref: ConceptRef,
        known: bool,
        now: datetime,
    ) -> Edge:
        """PATCH /v1/me/graph: applies even while learning is paused (the reader asked)."""
        template = await self._template(persona) if persona is not None else None

        async def body(t: Txn) -> Edge:
            if persona is not None and template is not None:
                path = demo_path(uid, persona)
                doc = (await t.get(path)) or _copy_template(template, now)
                knows = doc.get("knows") or {}
                current = knows.get(concept_id)
                edge = reader_events.correction(
                    edge_from_doc(current) if current else None, ref, _theta_map(doc), known, now
                )
                edge = Edge(**(vars(edge) | {"evidence": edge.evidence[-DEMO_MAX_EVIDENCE:]}))
                seeded = bool((current or {}).get("seeded"))
                entry = edge_to_doc(edge, ref.domain) | {"seeded": seeded}
                updated = doc | {
                    "knows": dict(knows) | {concept_id: entry},
                    "rev": int(doc.get("rev", 0)) + 1,
                    "updated_at": now,
                }
                fitted, _ = fit_demo_doc(updated, path, keep={concept_id})
                t.set(path, fitted)
                return edge
            reads = await t.get_all(
                [
                    user_path(uid),
                    sub_path(uid, "knows", concept_id),
                    sub_path(uid, "domains", ref.domain),
                ]
            )
            doc = reads[sub_path(uid, "knows", concept_id)]
            dom = reads[sub_path(uid, "domains", ref.domain)]
            theta = {ref.domain: float(dom["theta"])} if dom and "theta" in dom else {}
            edge = reader_events.correction(
                edge_from_doc(doc) if doc else None, ref, theta, known, now
            )
            t.set(sub_path(uid, "knows", concept_id), edge_to_doc(edge, ref.domain))
            user = UserProfile.model_validate(reads[user_path(uid)] or {})
            t.set(user_path(uid), user.model_copy(update={"rev": user.rev + 1}).model_dump())
            return edge

        return await self._store.run(body)

    async def record_view(
        self, uid: str, content_id: str, count: int, prompted: bool, now: datetime
    ) -> None:
        """A page load: the annotation trend (once per content per ISO week) and, when an
        uncertainty prompt was shown, today's prompt log (DESIGN §6.5, three per day). Nothing
        is written while learning is paused (no prompts are shown then either)."""
        week = iso_week(now)
        day = now.date().isoformat()

        async def body(t: Txn) -> None:
            reads = await t.get_all([user_path(uid), sub_path(uid, "weekly", week)])
            user_doc = reads[user_path(uid)]
            user = UserProfile.model_validate(user_doc or {})
            if user.learning_paused or not user.may_record:
                return
            today = user.prompts.get(day, [])
            if prompted and content_id not in today:
                updated = user.model_copy(update={"prompts": {day: [*today, content_id]}})
                t.set(user_path(uid), updated.model_dump())
            weekly = reads[sub_path(uid, "weekly", week)] or {}
            seen = list(weekly.get("content_ids", []))
            if content_id in seen or len(seen) >= MAX_WEEKLY_CONTENT_IDS:
                return
            weekly["content_ids"] = [*seen, content_id]
            weekly["annotations_shown"] = int(weekly.get("annotations_shown", 0)) + count
            t.set(sub_path(uid, "weekly", week), weekly)

        await self._store.run(body)

    # ------------------------------------------------------------ consent, onboarding, calibration

    async def record_consent(self, uid: str, version: str, now: datetime) -> UserProfile:
        return await self.update_settings(uid, {"consent": {"version": version, "at": now}})

    async def save_onboarding(
        self,
        uid: str,
        *,
        field: str,
        answers: Mapping[str, Any],
        thinks_in: list[str],
        theta: Mapping[str, float],
        interest: Mapping[str, float],
        liked: Mapping[str, tuple[ConceptRef, Any]],
        now: datetime,
    ) -> None:
        """One transaction: answers on users/{uid}, θ and interest per domain, and the liked
        articles' small nudges (`liked`: concept id → (ref, apply(edge | None, θ) -> Edge)).
        Re-submitting overwrites the answers and θ and restarts calibration."""
        domains = sorted(set(theta) | set(interest) | {r.domain for r, _ in liked.values()})

        async def body(t: Txn) -> None:
            reads = await t.get_all(
                [user_path(uid)]
                + [sub_path(uid, "domains", d) for d in domains]
                + [sub_path(uid, "knows", c) for c in liked]
            )
            user = UserProfile.model_validate(reads[user_path(uid)] or {})
            stored = {d: reads[sub_path(uid, "domains", d)] or {} for d in domains}
            new_theta = {d: float(stored[d].get("theta", 0.0)) for d in domains} | dict(theta)
            for d in domains:
                doc = stored[d] | {"theta": new_theta[d]}
                if d in interest:
                    doc["interest"] = interest[d]
                t.set(sub_path(uid, "domains", d), doc)
            for cid, (ref, apply) in liked.items():
                current = reads[sub_path(uid, "knows", cid)]
                edge = apply(edge_from_doc(current) if current else None, new_theta[ref.domain])
                t.set(sub_path(uid, "knows", cid), edge_to_doc(edge, ref.domain))
            updated = user.model_copy(
                update={
                    "field": field,
                    "onboarding": dict(answers),
                    "thinks_in": list(thinks_in),
                    "calibration": {"asked": [], "answers": 0},
                    "onboarding_done": False,
                    "rev": user.rev + 1,
                }
            )
            t.set(user_path(uid), updated.model_dump())

        await self._store.run(body)

    async def calibration_answer(
        self, uid: str, concept_id: str, ref: ConceptRef, apply: Any, total: int, now: datetime
    ) -> tuple[bool, int] | None:
        """Record one answer (`apply(edge | None, θ) -> (Edge, θ)`). None if this concept was
        already asked or calibration is finished; else (done, answers so far)."""

        async def body(t: Txn) -> tuple[bool, int] | None:
            reads = await t.get_all(
                [
                    user_path(uid),
                    sub_path(uid, "knows", concept_id),
                    sub_path(uid, "domains", ref.domain),
                ]
            )
            user = UserProfile.model_validate(reads[user_path(uid)] or {})
            asked = list(user.calibration.get("asked", []))
            if concept_id in asked or len(asked) >= total:
                return None
            current = reads[sub_path(uid, "knows", concept_id)]
            dom = reads[sub_path(uid, "domains", ref.domain)] or {}
            edge, theta = apply(
                edge_from_doc(current) if current else None, float(dom.get("theta", 0.0))
            )
            t.set(sub_path(uid, "knows", concept_id), edge_to_doc(edge, ref.domain))
            t.set(sub_path(uid, "domains", ref.domain), dom | {"theta": theta})
            asked.append(concept_id)
            done = len(asked) >= total
            updated = user.model_copy(
                update={
                    "calibration": {"asked": asked, "answers": len(asked)},
                    "onboarding_done": user.onboarding_done or done,
                    "rev": user.rev + 1,
                }
            )
            t.set(user_path(uid), updated.model_dump())
            return done, len(asked)

        return await self._store.run(body)

    async def finish_onboarding(self, uid: str) -> UserProfile:
        return await self.update_settings(uid, {"onboarding_done": True})

    # ------------------------------------------------------------ ingest cap

    async def reserve_ingest(
        self, uid: str, day: str, cap: int, global_path: str | None, global_cap: int
    ) -> bool:
        """Count one new URL against the reader's daily cap (and, for anonymous readers, the
        shared anonymous cap at `global_path`) before ingesting. False = over a cap."""
        return await self.reserve_daily("ingest_counts", uid, day, cap, global_path, global_cap)

    async def refund_ingest(self, uid: str, day: str, global_path: str | None) -> None:
        await self.refund_daily("ingest_counts", uid, day, global_path)

    async def reserve_daily(
        self,
        counter: str,
        uid: str,
        day: str,
        cap: int,
        global_path: str | None,
        global_cap: int,
    ) -> bool:
        """Count one unit against `users/{uid}/{counter}/{day}` (and the shared anonymous
        counter at `global_path`) in one transaction. False = over a cap, nothing written."""

        async def body(t: Txn) -> bool:
            mine_path = sub_path(uid, counter, day)
            reads = await t.get_all([mine_path] + ([global_path] if global_path else []))
            mine = int((reads[mine_path] or {}).get("count", 0))
            shared = int((reads[global_path] or {}).get("anonymous", 0)) if global_path else 0
            if mine >= cap or (global_path and shared >= global_cap):
                return False
            t.set(mine_path, {"count": mine + 1, "day": day})
            if global_path:
                t.set(global_path, (reads[global_path] or {}) | {"anonymous": shared + 1})
            return True

        return await self._store.run(body)

    async def refund_daily(self, counter: str, uid: str, day: str, global_path: str | None) -> None:
        async def body(t: Txn) -> None:
            mine_path = sub_path(uid, counter, day)
            reads = await t.get_all([mine_path] + ([global_path] if global_path else []))
            mine = int((reads[mine_path] or {}).get("count", 0))
            t.set(mine_path, {"count": max(0, mine - 1), "day": day})
            if global_path:
                doc = reads[global_path] or {}
                t.set(global_path, doc | {"anonymous": max(0, int(doc.get("anonymous", 0)) - 1)})

        await self._store.run(body)

    async def ingests_on(self, uid: str, day: str) -> int:
        doc = await self._store.get(sub_path(uid, "ingest_counts", day))
        return int((doc or {}).get("count", 0))

    # ------------------------------------------------------------ data rights

    async def export(self, uid: str) -> dict[str, Any]:
        out: dict[str, Any] = {"uid": uid, "user": await self._store.get(user_path(uid))}
        for name in USER_SUBCOLLECTIONS:
            out[name] = dict(await self._store.list(f"{user_path(uid)}/{name}"))
        return out

    async def delete(self, uid: str) -> int:
        return await self._store.delete_tree(user_path(uid))
