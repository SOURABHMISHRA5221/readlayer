"""Profile edits (DESIGN §15.3): pending previews, apply and undo, each in one transaction.

users/{uid}/profile_edits/{edit_id}  status pending | applied | undone, persona (demo session or
                                     null), the resolved ops (concept ids, never reader-typed
                                     text), expires_at (pending), the exact deltas once applied.

A signed-in reader's edit changes users/{uid} (+ knows, domains). A demo reader's edit changes only
this session's copy of the persona (users/{uid}/demo_graphs/{persona}) and the session's settings;
the persona template is never written, so the next demo session starts from the original.
"""

from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from app.graph.graph import ConceptGraph
from app.reader import profile_edit as pe
from app.reader.model import Edge
from app.reader.personas import PERSONA_THINKS_IN
from app.reader.state import PersonaKey
from app.store.docstore import DocStore, Txn
from app.store.reader_repo import (
    DEMO_MAX_EVIDENCE,
    EVENT_TTL,
    UserProfile,
    _copy_template,
    _theta_map,
    demo_path,
    edge_from_doc,
    edge_to_doc,
    fit_demo_doc,
    sub_path,
    user_path,
)

PENDING_TTL = timedelta(hours=1)
SETTING_KEYS = ("thinks_in", "explanation_style", "density", "learning_paused")
LIST_LIMIT = 10


class EditNotFound(Exception):
    pass


class EditNotApplicable(Exception):
    """Wrong status, expired, or another persona's edit."""


def _edit_path(uid: str, edit_id: str) -> str:
    return sub_path(uid, "profile_edits", edit_id)


def _settings(
    user: UserProfile, demo: Mapping[str, Any] | None, persona: PersonaKey | None
) -> dict[str, Any]:
    out = {
        "thinks_in": list(user.thinks_in),
        "explanation_style": user.explanation_style,
        "density": user.density,
        "learning_paused": user.learning_paused,
    }
    if persona is not None:
        out["thinks_in"] = list((demo or {}).get("thinks_in") or [PERSONA_THINKS_IN[persona]])
    return out


class ProfileEditRepo:
    def __init__(self, store: DocStore, template: Any = None) -> None:
        self._store = store
        self._template = template  # async (persona) -> template doc, for demo sessions

    # ------------------------------------------------------------ read-only state for previews

    async def state(
        self, uid: str, persona: PersonaKey | None, concept_ids: list[str], domains: list[str]
    ) -> tuple[dict[str, Edge], dict[str, float], dict[str, Any]]:
        user = UserProfile.model_validate(await self._store.get(user_path(uid)) or {})
        if persona is not None:
            demo = await self._store.get(demo_path(uid, persona))
            doc = demo if demo is not None else await self._template(persona)
            knows = doc.get("knows") or {}
            edges = {c: edge_from_doc(knows[c]) for c in concept_ids if c in knows}
            return edges, _theta_map(doc), _settings(user, demo, persona)
        edges: dict[str, Edge] = {}
        for c in concept_ids:
            if (doc := await self._store.get(sub_path(uid, "knows", c))) is not None:
                edges[c] = edge_from_doc(doc)
        theta: dict[str, float] = {}
        for d in domains:
            if (doc := await self._store.get(sub_path(uid, "domains", d))) and "theta" in doc:
                theta[d] = float(doc["theta"])
        return edges, theta, _settings(user, None, None)

    # ------------------------------------------------------------ pending edits

    async def save_pending(
        self, uid: str, edit_id: str, persona: PersonaKey | None, resolved: pe.Resolved,
        now: datetime,
    ) -> None:  # fmt: skip
        doc = {
            "status": "pending",
            "persona": persona,
            "resolved": resolved.to_doc(),
            "created_at": now,
            "expires_at": now + PENDING_TTL,
        }

        async def body(t: Txn) -> None:
            t.set(_edit_path(uid, edit_id), doc)

        await self._store.run(body)

    async def recent(self, uid: str, now: datetime) -> list[tuple[str, dict[str, Any]]]:
        """The latest applied/undone edits; expired pending ones are deleted on the way."""
        rows = await self._store.list(f"{user_path(uid)}/profile_edits")
        expired = [i for i, d in rows if d.get("status") == "pending" and d["expires_at"] <= now]
        if expired:

            async def body(t: Txn) -> None:
                for i in expired:
                    t.delete(_edit_path(uid, i))

            await self._store.run(body)
        kept = [(i, d) for i, d in rows if i not in expired and d.get("status") != "pending"]
        kept.sort(key=lambda r: r[1].get("applied_at") or r[1]["created_at"], reverse=True)
        return kept[:LIST_LIMIT]

    # ------------------------------------------------------------ apply and undo

    async def apply(
        self, uid: str, persona: PersonaKey | None, edit_id: str, graph: ConceptGraph,
        now: datetime,
    ) -> dict[str, Any]:  # fmt: skip
        template = await self._template(persona) if persona is not None else None

        async def body(t: Txn) -> dict[str, Any]:
            edit = await t.get(_edit_path(uid, edit_id))
            if edit is None:
                raise EditNotFound(edit_id)
            if (
                edit["status"] != "pending"
                or edit["expires_at"] <= now
                or edit["persona"] != persona
            ):
                raise EditNotApplicable(edit_id)
            resolved = pe.Resolved.from_doc(edit["resolved"])
            touched = pe.touched(resolved, graph)
            domains = sorted(set(resolved.domains) | {c.domain for c in touched.values()})
            if persona is not None:
                applied = await self._apply_demo(
                    t, uid, persona, template, resolved, touched, graph, now
                )  # noqa: E501
            else:
                applied = await self._apply_user(t, uid, resolved, touched, domains, graph, now)
            done = edit | {
                "status": "applied",
                "applied_at": now,
                "deltas": pe.deltas_to_doc(applied),
            }
            done.pop("expires_at", None)
            t.set(_edit_path(uid, edit_id), done)
            t.set(
                sub_path(uid, "events", f"profile_edit-{edit_id}"),
                {"type": "profile_edit", "at": now, "received_at": now,
                 "expire_at": now + EVENT_TTL, "edit_id": edit_id, "persona": persona},
            )  # fmt: skip
            return done

        return await self._store.run(body)

    async def _apply_user(
        self, t: Txn, uid: str, resolved: pe.Resolved, touched: Mapping[str, Any],
        domains: list[str], graph: ConceptGraph, now: datetime,
    ) -> pe.Applied:  # fmt: skip
        reads = await t.get_all(
            [user_path(uid)]
            + [sub_path(uid, "knows", c) for c in touched]
            + [sub_path(uid, "domains", d) for d in domains]
        )
        user = UserProfile.model_validate(reads[user_path(uid)] or {})
        edges = {
            c: edge_from_doc(doc) for c in touched if (doc := reads[sub_path(uid, "knows", c)])
        }
        stored = {d: reads[sub_path(uid, "domains", d)] or {} for d in domains}
        theta = {d: float(doc["theta"]) for d, doc in stored.items() if "theta" in doc}
        applied = pe.apply(resolved, graph, edges, theta, _settings(user, None, None), now)
        for cid, edge in applied.edges.items():
            t.set(sub_path(uid, "knows", cid), edge_to_doc(edge, applied.edge_deltas[cid].domain))
        for d, th in applied.theta.items():
            t.set(sub_path(uid, "domains", d), stored.get(d, {}) | {"theta": th})
        t.set(
            user_path(uid),
            user.model_copy(update=applied.settings | {"rev": user.rev + 1}).model_dump(),
        )
        return applied

    async def _apply_demo(
        self, t: Txn, uid: str, persona: PersonaKey, template: Any, resolved: pe.Resolved,
        touched: Mapping[str, Any], graph: ConceptGraph, now: datetime,
    ) -> pe.Applied:  # fmt: skip
        path = demo_path(uid, persona)
        reads = await t.get_all([user_path(uid), path])
        user = UserProfile.model_validate(reads[user_path(uid)] or {})
        doc = reads[path] or _copy_template(template, now)
        knows = doc.get("knows") or {}
        edges = {c: edge_from_doc(knows[c]) for c in touched if c in knows}
        applied = pe.apply(
            resolved, graph, edges, _theta_map(doc), _settings(user, doc, persona), now
        )  # noqa: E501
        new_knows = dict(knows)
        for cid, edge in applied.edges.items():
            trimmed = Edge(**(vars(edge) | {"evidence": edge.evidence[-DEMO_MAX_EVIDENCE:]}))
            seeded = bool(knows.get(cid, {}).get("seeded"))
            new_knows[cid] = edge_to_doc(trimmed, applied.edge_deltas[cid].domain) | {
                "seeded": seeded
            }
        session = {k: v for k, v in applied.settings.items() if k != "thinks_in"}
        updated = doc | {
            "knows": new_knows,
            "theta": _theta_map(doc) | applied.theta,
            "rev": int(doc.get("rev", 0)) + 1,
            "updated_at": now,
        }
        if "thinks_in" in applied.settings:  # session-only frame for this persona
            updated["thinks_in"] = applied.settings["thinks_in"]
        fitted, _ = fit_demo_doc(updated, path, keep=set(applied.edges))
        t.set(path, fitted)
        if session:
            t.set(user_path(uid), user.model_copy(update=session).model_dump())
        return applied

    async def undo(
        self, uid: str, persona: PersonaKey | None, edit_id: str, now: datetime
    ) -> dict[str, Any]:
        async def body(t: Txn) -> dict[str, Any]:
            edit = await t.get(_edit_path(uid, edit_id))
            if edit is None:
                raise EditNotFound(edit_id)
            if edit["status"] != "applied" or edit["persona"] != persona:
                raise EditNotApplicable(edit_id)
            edge_deltas, theta_deltas = pe.deltas_from_doc(edit["deltas"])
            applied_settings = edit["deltas"]["settings"]
            previous = edit["deltas"]["previous_settings"]
            at = edit["applied_at"]
            if persona is not None:
                await self._undo_demo(
                    t, uid, persona, edge_deltas, theta_deltas, applied_settings, previous, at
                )  # noqa: E501
            else:
                await self._undo_user(
                    t, uid, edge_deltas, theta_deltas, applied_settings, previous, at
                )  # noqa: E501
            done = edit | {"status": "undone", "undone_at": now}
            t.set(_edit_path(uid, edit_id), done)
            return done

        return await self._store.run(body)

    async def _undo_user(self, t, uid, edge_deltas, theta_deltas, applied_settings, previous, at):  # type: ignore[no-untyped-def]
        domains = sorted(set(theta_deltas))
        reads = await t.get_all(
            [user_path(uid)]
            + [sub_path(uid, "knows", c) for c in edge_deltas]
            + [sub_path(uid, "domains", d) for d in domains]
        )
        user = UserProfile.model_validate(reads[user_path(uid)] or {})
        edges = {
            c: edge_from_doc(doc) for c in edge_deltas if (doc := reads[sub_path(uid, "knows", c)])
        }
        stored = {d: reads[sub_path(uid, "domains", d)] or {} for d in domains}
        theta = {d: float(doc.get("theta", 0.0)) for d, doc in stored.items()}
        out = pe.undo(
            edge_deltas, theta_deltas, applied_settings, previous, at, edges, theta,
            _settings(user, None, None),
        )  # fmt: skip
        for cid, edge in out.edges.items():
            t.set(sub_path(uid, "knows", cid), edge_to_doc(edge, edge_deltas[cid].domain))
        for cid in out.removed:
            t.delete(sub_path(uid, "knows", cid))
        for d, th in out.theta.items():
            t.set(sub_path(uid, "domains", d), stored.get(d, {}) | {"theta": th})
        t.set(
            user_path(uid),
            user.model_copy(update=out.settings | {"rev": user.rev + 1}).model_dump(),
        )

    async def _undo_demo(
        self, t, uid, persona, edge_deltas, theta_deltas, applied_settings, previous, at
    ):  # type: ignore[no-untyped-def]
        path = demo_path(uid, persona)
        reads = await t.get_all([user_path(uid), path])
        user = UserProfile.model_validate(reads[user_path(uid)] or {})
        doc = reads[path]
        if doc is None:  # reset since: nothing of this edit is left
            return
        knows = doc.get("knows") or {}
        edges = {c: edge_from_doc(knows[c]) for c in edge_deltas if c in knows}
        out = pe.undo(
            edge_deltas, theta_deltas, applied_settings, previous, at, edges, _theta_map(doc),
            _settings(user, doc, persona),
        )  # fmt: skip
        new_knows = dict(knows)
        for cid, edge in out.edges.items():
            seeded = bool(knows.get(cid, {}).get("seeded"))
            new_knows[cid] = edge_to_doc(edge, edge_deltas[cid].domain) | {"seeded": seeded}
        for cid in out.removed:
            new_knows.pop(cid, None)
        updated = doc | {
            "knows": new_knows,
            "theta": _theta_map(doc) | out.theta,
            "rev": int(doc.get("rev", 0)) + 1,
        }
        if "thinks_in" in out.settings:
            restored = out.settings["thinks_in"]
            if restored == [PERSONA_THINKS_IN[persona]]:
                updated.pop("thinks_in", None)
            else:
                updated["thinks_in"] = restored
        t.set(path, updated)
        session = {k: v for k, v in out.settings.items() if k != "thinks_in"}
        if session:
            t.set(user_path(uid), user.model_copy(update=session).model_dump())

    # ------------------------------------------------------------ demo reset

    async def reset_demo(self, uid: str, persona: PersonaKey) -> int:
        """Back to the original persona for this session: its copy and its edits go, and the
        session settings its applied edits changed return to what they were before the first."""
        rows = await self._store.list(f"{user_path(uid)}/profile_edits")
        mine = [(i, d) for i, d in rows if d.get("persona") == persona]
        applied = sorted(
            (d for _, d in mine if d.get("status") == "applied"), key=lambda d: d["applied_at"]
        )
        restore: dict[str, Any] = {}
        for d in applied:  # the earliest edit's "before" wins
            for k, v in d["deltas"]["previous_settings"].items():
                if k != "thinks_in":  # the session frame lives on the persona copy, deleted here
                    restore.setdefault(k, v)

        async def body(t: Txn) -> int:
            user = UserProfile.model_validate(await t.get(user_path(uid)) or {})
            t.delete(demo_path(uid, persona))
            for i, _ in mine:
                t.delete(_edit_path(uid, i))
            if restore:
                t.set(user_path(uid), user.model_copy(update=restore).model_dump())
            return len(mine)

        return await self._store.run(body)
