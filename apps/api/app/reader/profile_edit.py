"""Edit a reader profile with a prompt (DESIGN §15.3): the whitelist of ops the model may return,
and how a resolved edit applies to (and is undone from) the reader model. Pure: no I/O.

The model returns ops with concept **names** only; names are resolved to concept ids through
the graph linker before anything is applied. Applying records the exact deltas (Δα/Δβ per
concept, Δθ per domain, previous settings) so undo can restore them.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.graph.graph import ConceptGraph
from app.graph.models import DOMAINS, Concept, Domain
from app.reader import model
from app.reader.model import Edge
from app.reader.onboarding import LEVEL_THETA, Level
from app.reader.state import Density, ExplanationStyle, ThinksIn

MAX_OPS = 20
MAX_NAMES_PER_OP = 30
MAX_NAMES_PER_EDIT = 30  # distinct names across all ops, checked before any linking
MAX_TEXT_CHARS = 500
CONCEPT_WEIGHT = 3.0  # DESIGN §4: profile_edit concept claim
DOMAIN_WEIGHT = 2.0  # per core concept
CORE_CONCEPTS = 10
THETA_STEP = 0.5  # θ ← θ + 0.5·(target − θ)
_ID_LIKE = re.compile(r"^c_[a-z0-9_]+$")

Name = Annotated[str, Field(min_length=1, max_length=80)]


class _Op(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SetDomainLevel(_Op):
    op: Literal["set_domain_level"]
    domain: Domain
    level: Level


class MarkConcepts(_Op):
    op: Literal["mark_concepts"]
    names: list[Name] = Field(min_length=1, max_length=MAX_NAMES_PER_OP)
    state: Literal["known", "unknown"]


class SetThinksIn(_Op):
    op: Literal["set_thinks_in"]
    domains: list[ThinksIn] = Field(min_length=1, max_length=3)


class SetExplanationStyle(_Op):
    op: Literal["set_explanation_style"]
    length: ExplanationStyle


class SetDensity(_Op):
    op: Literal["set_density"]
    density: Density


class PauseLearning(_Op):
    op: Literal["pause_learning"]
    paused: bool


Op = Annotated[
    SetDomainLevel | MarkConcepts | SetThinksIn | SetExplanationStyle | SetDensity | PauseLearning,
    Field(discriminator="op"),
]


class ProfileEditOps(BaseModel):
    """What `profile_edit` returns. Anything else fails validation and nothing is applied."""

    model_config = ConfigDict(extra="forbid")
    ops: list[Op] = Field(max_length=MAX_OPS)


OpName = Literal[
    "set_domain_level", "mark_concepts", "set_thinks_in", "set_explanation_style", "set_density",
    "pause_learning",
]  # fmt: skip


class FlatOp(BaseModel):
    """What the model fills. Vertex rejects tagged-union response schemas and, past a size,
    schemas full of nullable (anyOf) fields, so every optional field is a plain enum or list with
    an empty default. `strict()` maps it onto the op's own schema and re-validates."""

    model_config = ConfigDict(extra="forbid")
    op: OpName
    # One flat enum ("" or a taxonomy domain): Vertex rejects anyOf unions in this schema.
    domain: Literal[("", *DOMAINS)] = ""  # type: ignore[valid-type]
    level: Literal["", "new", "some", "comfortable", "expert"] = ""
    names: list[Name] = Field(default_factory=list, max_length=MAX_NAMES_PER_OP)
    state: Literal["", "known", "unknown"] = ""
    domains: list[ThinksIn] = Field(default_factory=list, max_length=3)
    length: Literal["", "short", "normal", "detailed"] = ""
    density: Literal["", "minimal", "balanced", "guided"] = ""
    paused: Literal["", "yes", "no"] = ""


class ModelEditOps(BaseModel):
    """The `profile_edit` response schema. No maxItems here: Vertex rejects an outer array limit
    alongside the inner ones; `strict()` enforces MAX_OPS (ProfileEditOps)."""

    model_config = ConfigDict(extra="forbid")
    ops: list[FlatOp]


def strict(flat: ModelEditOps) -> ProfileEditOps:
    """Each op against its own schema: a field that doesn't belong to the op, or a missing one,
    rejects the whole edit (pydantic ValidationError)."""
    ops = []
    for op in flat.ops:
        fields = op.model_dump(exclude_defaults=True)
        fields["op"] = op.op
        if "paused" in fields:
            fields["paused"] = fields["paused"] == "yes"
        ops.append(fields)
    return ProfileEditOps.model_validate({"ops": ops})


class EditRejected(ValueError):
    """The ops are well-formed but not acceptable (too many names, an id in place of a name)."""


def distinct_names(ops: Sequence[Any]) -> list[str]:
    seen: dict[str, str] = {}
    for op in ops:
        if isinstance(op, MarkConcepts):
            for n in op.names:
                seen.setdefault(n.strip().casefold(), n.strip())
    return list(seen.values())


def check_names(ops: Sequence[Any]) -> list[str]:
    """The distinct names to resolve, or EditRejected: over the per-edit cap, or the model
    supplied something shaped like a concept id (ids only ever come from the linker)."""
    names = distinct_names(ops)
    if len(names) > MAX_NAMES_PER_EDIT:
        raise EditRejected("too_many_concepts")
    if any(_ID_LIKE.match(n) for n in names):
        raise EditRejected("concept_id_from_model")
    return names


# ---------------------------------------------------------------- resolved edits


@dataclass(frozen=True)
class Resolved:
    """An edit with names replaced by concept ids (unresolved names dropped)."""

    concepts: dict[str, bool] = field(default_factory=dict)  # concept id → known
    domains: dict[str, Level] = field(default_factory=dict)
    settings: dict[str, Any] = field(default_factory=dict)  # thinks_in/explanation_style/...

    def to_doc(self) -> dict[str, Any]:
        return {"concepts": self.concepts, "domains": self.domains, "settings": self.settings}

    @classmethod
    def from_doc(cls, doc: Mapping[str, Any]) -> "Resolved":
        return cls(dict(doc["concepts"]), dict(doc["domains"]), dict(doc["settings"]))


def resolve(ops: Sequence[Any], ids: Mapping[str, str]) -> Resolved:
    """Later ops win over earlier ones for the same target. `ids` maps a casefolded name to a
    concept id; names missing from it are dropped (reported as unresolved by the caller)."""
    concepts: dict[str, bool] = {}
    domains: dict[str, Level] = {}
    settings: dict[str, Any] = {}
    for op in ops:
        if isinstance(op, MarkConcepts):
            for n in op.names:
                if (cid := ids.get(n.strip().casefold())) is not None:
                    concepts[cid] = op.state == "known"
        elif isinstance(op, SetDomainLevel):
            domains[op.domain] = op.level
        elif isinstance(op, SetThinksIn):
            settings["thinks_in"] = list(dict.fromkeys(op.domains))
        elif isinstance(op, SetExplanationStyle):
            settings["explanation_style"] = op.length
        elif isinstance(op, SetDensity):
            settings["density"] = op.density
        elif isinstance(op, PauseLearning):
            settings["learning_paused"] = op.paused
    return Resolved(concepts, domains, settings)


def core_concepts(graph: ConceptGraph, domain: str) -> list[Concept]:
    in_domain = [c for c in graph.concepts if c.domain == domain]
    return sorted(in_domain, key=lambda c: (-c.doc_freq, c.id))[:CORE_CONCEPTS]


@dataclass(frozen=True)
class EdgeDelta:
    domain: str
    d_alpha: float
    d_beta: float
    created: bool  # the edit made this edge (no evidence before it)
    floor_alpha: float
    floor_beta: float


@dataclass(frozen=True)
class Applied:
    edges: dict[str, Edge]  # changed edges, final values
    theta: dict[str, float]  # changed domains, final values
    settings: dict[str, Any]  # new values
    edge_deltas: dict[str, EdgeDelta]
    theta_deltas: dict[str, float]
    previous_settings: dict[str, Any]


def touched(resolved: Resolved, graph: ConceptGraph) -> dict[str, Concept]:
    """Every concept an apply may change: named ones and each set domain's core concepts."""
    out = {cid: c for cid in resolved.concepts if (c := graph.get(cid)) is not None}
    for d in resolved.domains:
        out |= {c.id: c for c in core_concepts(graph, d)}
    return out


def apply(
    resolved: Resolved,
    graph: ConceptGraph,
    edges: Mapping[str, Edge],
    theta: Mapping[str, float],
    settings: Mapping[str, Any],
    now: datetime,
) -> Applied:
    new_theta: dict[str, float] = {}
    theta_deltas: dict[str, float] = {}
    for d, level in resolved.domains.items():
        before = theta.get(d, 0.0)
        after = before + THETA_STEP * (LEVEL_THETA[level] - before)
        new_theta[d], theta_deltas[d] = after, after - before
    weights: dict[str, tuple[str, float]] = {}  # concept id → (evidence kind, signed weight)
    for d, level in resolved.domains.items():
        target = LEVEL_THETA[level]
        for c in core_concepts(graph, d):
            w = DOMAIN_WEIGHT if c.base_difficulty <= target else -DOMAIN_WEIGHT
            weights[c.id] = ("profile_edit_domain", w)
    for cid, known in resolved.concepts.items():  # a named concept wins over a domain claim
        weights[cid] = ("profile_edit_concept", CONCEPT_WEIGHT if known else -CONCEPT_WEIGHT)
    new_edges: dict[str, Edge] = {}
    deltas: dict[str, EdgeDelta] = {}
    for cid, (kind, w) in sorted(weights.items()):
        c = graph.get(cid)
        if c is None:
            continue
        th = new_theta.get(c.domain, theta.get(c.domain, 0.0))
        p0 = model.prior(th, c.base_difficulty)
        old = edges.get(cid)
        base = old or model.init_edge(p0, now)
        new = model.apply_evidence(base, p0, kind, w, now)
        new_edges[cid] = new
        deltas[cid] = EdgeDelta(
            c.domain,
            new.alpha - base.alpha,
            new.beta - base.beta,
            old is None,
            min(base.alpha, model.K_PRIOR * p0),
            min(base.beta, model.K_PRIOR * (1 - p0)),
        )
    previous = {k: settings.get(k) for k in resolved.settings}
    return Applied(new_edges, new_theta, dict(resolved.settings), deltas, theta_deltas, previous)


@dataclass(frozen=True)
class Undone:
    edges: dict[str, Edge]  # edges to write back
    removed: list[str]  # edges the edit created and nothing touched since: delete
    theta: dict[str, float]
    settings: dict[str, Any]  # settings to restore


def undo(
    edge_deltas: Mapping[str, EdgeDelta],
    theta_deltas: Mapping[str, float],
    applied_settings: Mapping[str, Any],
    previous_settings: Mapping[str, Any],
    applied_at: datetime,
    edges: Mapping[str, Edge],
    theta: Mapping[str, float],
    settings: Mapping[str, Any],
) -> Undone:
    """Subtract the recorded deltas (α, β floored), revert Δθ, restore settings the reader hasn't
    changed since. Evidence added after the edit stays; an edge the edit created and nothing has
    touched since is removed. An edge that no longer exists (e.g. a demo doc dropped it to stay
    under its size guard) is skipped, never recreated."""
    out_edges: dict[str, Edge] = {}
    removed: list[str] = []
    for cid, d in edge_deltas.items():
        edge = edges.get(cid)
        if edge is None:
            continue
        mine = [
            e for e in edge.evidence if e.at == applied_at and e.type.startswith("profile_edit")
        ]
        later = [e for e in edge.evidence if e.at > applied_at]
        if d.created and not later:
            removed.append(cid)
            continue
        alpha = max(edge.alpha - d.d_alpha, d.floor_alpha)
        beta = max(edge.beta - d.d_beta, d.floor_beta)
        kept = tuple(e for e in edge.evidence if e not in mine)
        out_edges[cid] = replace(
            edge, alpha=alpha, beta=beta, evidence=kept, band=model.band_of(alpha / (alpha + beta))
        )
    out_theta = {d: theta.get(d, 0.0) - delta for d, delta in theta_deltas.items()}
    restore = {
        k: previous_settings.get(k)
        for k, v in applied_settings.items()
        if settings.get(k) == v  # unchanged since the edit
    }
    return Undone(out_edges, removed, out_theta, restore)


# ---------------------------------------------------------------- (de)serialising deltas


def deltas_to_doc(a: Applied) -> dict[str, Any]:
    return {
        "edges": {
            cid: {
                "domain": d.domain, "d_alpha": d.d_alpha, "d_beta": d.d_beta,
                "created": d.created, "floor_alpha": d.floor_alpha, "floor_beta": d.floor_beta,
            }
            for cid, d in a.edge_deltas.items()
        },
        "theta": a.theta_deltas,
        "settings": a.settings,
        "previous_settings": a.previous_settings,
    }  # fmt: skip


def deltas_from_doc(doc: Mapping[str, Any]) -> tuple[dict[str, EdgeDelta], dict[str, float]]:
    edges = {cid: EdgeDelta(**d) for cid, d in doc["edges"].items()}
    return edges, dict(doc["theta"])


# ---------------------------------------------------------------- preview


def preview(
    resolved: Resolved,
    graph: ConceptGraph,
    applied: Applied,
    theta: Mapping[str, float],
    unresolved: Sequence[str],
) -> dict[str, Any]:
    """What the reader sees before Apply: domains θ before → after, concepts by direction,
    settings before → after. Labels only, from the graph; never anything the reader typed
    except `unresolved` (returned, never stored)."""

    def labels(ids: list[str]) -> list[dict[str, str]]:
        return [{"concept_id": i, "label": graph.get(i).label} for i in ids if graph.get(i)]  # type: ignore[union-attr]

    up = sorted(c for c, d in applied.edge_deltas.items() if d.d_alpha > 0)
    down = sorted(c for c, d in applied.edge_deltas.items() if d.d_beta > 0)
    return {
        "domains": [
            {"domain": d, "before": round(theta.get(d, 0.0), 3), "after": round(v, 3)}
            for d, v in sorted(applied.theta.items())
        ],
        "known": labels(up),
        "unknown": labels(down),
        "settings": [
            {"setting": k, "before": applied.previous_settings.get(k), "after": v}
            for k, v in sorted(applied.settings.items())
            if applied.previous_settings.get(k) != v  # no "software → software"
        ],
        "unresolved": list(unresolved),
    }
