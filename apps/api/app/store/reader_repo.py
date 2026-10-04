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

Export and delete both walk USER_SUBCOLLECTIONS; a test fails if anything is written under
`users/{uid}` outside it.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.reader import events as reader_events
from app.reader.events import ConceptRef, ReaderEvent
from app.reader.model import Edge, Evidence
from app.reader.profile import iso_week
from app.store.docstore import Doc, DocStore, Txn

USER_SUBCOLLECTIONS = (
    "domains",
    "knows",
    "events",
    "weekly",
    "profile_edits",
    "rec_signals",
    "ingest_counts",
)
EVENT_TTL = timedelta(days=90)
MAX_WEEKLY_CONTENT_IDS = 500

Density = Literal["minimal", "balanced", "guided"]
ExplanationStyle = Literal["short", "normal", "detailed"]


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


@dataclass(frozen=True)
class EventsResult:
    applied: int
    ignored: int
    paused: bool


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

    # ------------------------------------------------------------ events and corrections

    async def apply_events(
        self,
        uid: str,
        events: list[ReaderEvent],
        refs: Mapping[str, ConceptRef],
        base_theta: Mapping[str, float],
        now: datetime,
        *,
        theta_fixed: bool,
    ) -> EventsResult:
        """One transaction: pause check, idempotency, KNOWS + θ + weekly updates, event log."""

        async def body(t: Txn) -> EventsResult:
            user = UserProfile.model_validate(await t.get(user_path(uid)) or {})
            if user.learning_paused:
                return EventsResult(0, len(events), True)
            stored = await t.get_all([sub_path(uid, "events", e.id) for e in events])
            fresh = [e for e in events if stored[sub_path(uid, "events", e.id)] is None]
            cids = sorted({e.concept_id for e in fresh if e.concept_id in refs})
            domains = sorted({refs[c].domain for c in cids})
            week = iso_week(now)
            reads = await t.get_all(
                [sub_path(uid, "knows", c) for c in cids]
                + [sub_path(uid, "domains", d) for d in domains]
                + [sub_path(uid, "weekly", week)]
            )
            edges = {
                c: edge_from_doc(doc)
                for c in cids
                if (doc := reads[sub_path(uid, "knows", c)]) is not None
            }
            stored_domains = {d: reads[sub_path(uid, "domains", d)] for d in domains}
            theta = dict(base_theta)
            if not theta_fixed:
                theta |= {
                    d: float(doc["theta"])
                    for d, doc in stored_domains.items()
                    if doc and "theta" in doc
                }
            out = reader_events.apply_events(
                fresh, edges, theta, refs, now, theta_fixed=theta_fixed
            )
            for cid, edge in out.edges.items():
                t.set(sub_path(uid, "knows", cid), edge_to_doc(edge, refs[cid].domain))
            for d, th in out.theta.items():
                t.set(sub_path(uid, "domains", d), (stored_domains.get(d) or {}) | {"theta": th})
            if out.words_read:
                weekly = reads[sub_path(uid, "weekly", week)] or {}
                weekly["words_read"] = int(weekly.get("words_read", 0)) + out.words_read
                t.set(sub_path(uid, "weekly", week), weekly)
            applied = set(out.applied)
            for e in fresh:
                if e.id in applied:
                    t.set(sub_path(uid, "events", e.id), _event_doc(e, now))
            return EventsResult(len(out.applied), len(events) - len(out.applied), False)

        return await self._store.run(body)

    async def correct(
        self,
        uid: str,
        concept_id: str,
        ref: ConceptRef,
        known: bool,
        base_theta: Mapping[str, float],
        now: datetime,
        *,
        theta_fixed: bool,
    ) -> Edge:
        """PATCH /v1/me/graph: applies even while learning is paused (the reader asked)."""

        async def body(t: Txn) -> Edge:
            reads = await t.get_all(
                [sub_path(uid, "knows", concept_id), sub_path(uid, "domains", ref.domain)]
            )
            doc = reads[sub_path(uid, "knows", concept_id)]
            dom = reads[sub_path(uid, "domains", ref.domain)]
            theta = dict(base_theta)
            if not theta_fixed and dom and "theta" in dom:
                theta[ref.domain] = float(dom["theta"])
            edge = reader_events.correction(
                edge_from_doc(doc) if doc else None, ref, theta, known, now
            )
            t.set(sub_path(uid, "knows", concept_id), edge_to_doc(edge, ref.domain))
            return edge

        return await self._store.run(body)

    async def record_annotations_shown(
        self, uid: str, content_id: str, count: int, now: datetime
    ) -> None:
        """Once per content per ISO week; nothing while learning is paused."""
        week = iso_week(now)

        async def body(t: Txn) -> None:
            reads = await t.get_all([user_path(uid), sub_path(uid, "weekly", week)])
            if UserProfile.model_validate(reads[user_path(uid)] or {}).learning_paused:
                return
            weekly = reads[sub_path(uid, "weekly", week)] or {}
            seen = list(weekly.get("content_ids", []))
            if content_id in seen or len(seen) >= MAX_WEEKLY_CONTENT_IDS:
                return
            weekly["content_ids"] = [*seen, content_id]
            weekly["annotations_shown"] = int(weekly.get("annotations_shown", 0)) + count
            t.set(sub_path(uid, "weekly", week), weekly)

        await self._store.run(body)

    # ------------------------------------------------------------ ingest cap

    async def reserve_ingest(
        self, uid: str, day: str, cap: int, global_path: str | None, global_cap: int
    ) -> bool:
        """Count one new URL against the reader's daily cap (and, for anonymous readers, the
        shared anonymous cap at `global_path`) before ingesting. False = over a cap."""

        async def body(t: Txn) -> bool:
            mine_path = sub_path(uid, "ingest_counts", day)
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

    async def refund_ingest(self, uid: str, day: str, global_path: str | None) -> None:
        async def body(t: Txn) -> None:
            mine_path = sub_path(uid, "ingest_counts", day)
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
