"""Hand corrections to the concept graph, data/graph_overrides.yaml (committed).

The build applies them on every run, so a rebuild can't undo a fix: `never_merge` pairs are
never joined by dedupe, `split` entries are pulled out of whatever concept they merged into and
become their own concept, `rename` entries replace a concept's label (its id follows the label).
M2.2 adds `remove_alias` (strip aliases that cause wrong exact-match links), `add` (hand-written
concepts the corpus never produced) and `never_merge_kind` (named organisations never absorb a
differently-labelled concept). `scripts.apply_overrides` patches an already-built graph the same
way. Pure: no I/O but `load`.
"""

from collections.abc import Callable, Iterable, Sequence
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from app.graph.build import KEEP_KINDS, difficulty, normalize_label
from app.graph.models import Concept, ConceptGraphFile, Domain


class Split(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    label: str
    from_: str = Field(alias="from")
    aliases: list[str] = Field(default_factory=list)

    @property
    def keys(self) -> set[str]:
        return {normalize_label(x) for x in [self.label, *self.aliases]}


class Rename(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_: str = Field(alias="from")
    to: str


class RemoveAlias(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str  # the concept to strip them from
    aliases: list[str] = Field(min_length=1)


class AddConcept(BaseModel):
    """A concept written by hand: our own definition, never copied text."""

    model_config = ConfigDict(extra="forbid")

    label: str
    aliases: list[str] = Field(default_factory=list)
    domain: Domain
    kind: str
    jurisdiction: str = Field(default="global", pattern=r"^([A-Z]{2}|global)$")
    specialization: int = Field(ge=1, le=5)
    definition: str = Field(min_length=20)
    prerequisites: list[str] = Field(default_factory=list, max_length=3)  # existing labels

    def model_post_init(self, _context: object) -> None:
        if self.kind not in KEEP_KINDS:
            raise ValueError(f"add {self.label!r}: kind {self.kind!r} is not a kept kind")


class Overrides(BaseModel):
    model_config = ConfigDict(extra="forbid")

    never_merge: list[tuple[str, str]] = Field(default_factory=list)
    split: list[Split] = Field(default_factory=list)
    rename: list[Rename] = Field(default_factory=list)
    remove_alias: list[RemoveAlias] = Field(default_factory=list)
    add: list[AddConcept] = Field(default_factory=list)
    never_merge_kind: list[str] = Field(default_factory=list)

    def merge_refused(self, existing: Concept, candidate_label: str) -> bool:
        """A differently-labelled candidate never merges into a named organisation (Russell
        Indexes into S&P Dow Jones Indices). Exact label/alias identity is the exact-match path,
        never a merge, so it isn't affected."""
        if existing.kind not in self.never_merge_kind:
            return False
        names = {normalize_label(x) for x in [existing.label, *existing.aliases]}
        return normalize_label(candidate_label) not in names

    @classmethod
    def load(cls, path: Path) -> "Overrides":
        if not path.exists():
            return cls()
        return cls.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})

    def blocked_pairs(self) -> set[frozenset[str]]:
        """Normalised label pairs dedupe must not merge (splits imply never-merge too)."""
        pairs = {frozenset(map(normalize_label, p)) for p in self.never_merge}
        for s in self.split:
            pairs |= {frozenset({k, normalize_label(s.from_)}) for k in s.keys}
        return pairs

    def renamed(self, label: str) -> str | None:
        key = normalize_label(label)
        return next((r.to for r in self.rename if normalize_label(r.from_) == key), None)


def filter_pairs(
    pairs: Iterable[tuple[int, int]], keys: Sequence[str], overrides: Overrides
) -> list[tuple[int, int]]:
    """Drop merge pairs whose two candidate keys form a blocked pair."""
    blocked = overrides.blocked_pairs()
    return [(i, j) for i, j in pairs if frozenset({keys[i], keys[j]}) not in blocked]


def split_groups(
    groups: list[list[int]], keys: Sequence[str], overrides: Overrides
) -> list[list[int]]:
    """Pull each split's members out of their merged groups into one group of their own."""
    out = [list(g) for g in groups]
    for s in overrides.split:
        wanted = s.keys
        taken = [i for g in out for i in g if keys[i] in wanted]
        if not taken:
            continue
        out = [[i for i in g if keys[i] not in wanted] for g in out]
        out = [g for g in out if g] + [taken]
    return out


# ---------------------------------------------------------------- patching a built graph


def _without(aliases: list[str], keys: set[str]) -> list[str]:
    return [a for a in aliases if normalize_label(a) not in keys]


def patch_renames(
    file: ConceptGraphFile, overrides: Overrides, new_id: Callable[[str, set[str]], str]
) -> tuple[ConceptGraphFile, dict[str, str]]:
    """Apply renames. Returns the new file and old id -> new id for concepts whose id changed."""
    concepts = list(file.concepts)
    taken = {c.id for c in concepts}
    moved: dict[str, str] = {}
    for i, c in enumerate(concepts):
        to = overrides.renamed(c.label)
        if to is None or to == c.label:
            continue
        cid = new_id(to, taken - {c.id})
        taken = (taken - {c.id}) | {cid}
        drop = {normalize_label(c.label), normalize_label(to)}
        concepts[i] = c.model_copy(
            update={"id": cid, "label": to, "aliases": _without(c.aliases, drop)}
        )
        if cid != c.id:
            moved[c.id] = cid
    concepts = [
        c.model_copy(update={"prerequisites": [moved.get(p, p) for p in c.prerequisites]})
        for c in concepts
    ]
    return file.model_copy(update={"concepts": concepts}), moved


def patch_split_sources(
    file: ConceptGraphFile, overrides: Overrides
) -> tuple[ConceptGraphFile, list[tuple[Split, str]]]:
    """Strip each split's label and aliases from its source concept.

    Returns the new file and (split, source id) for splits still needing a concept of their own.
    """
    concepts = list(file.concepts)
    existing = {normalize_label(c.label) for c in concepts}
    todo: list[tuple[Split, str]] = []
    for s in overrides.split:
        src = next(
            (
                i
                for i, c in enumerate(concepts)
                if normalize_label(c.label) == normalize_label(s.from_)
            ),
            None,
        )
        if src is not None:
            concepts[src] = concepts[src].model_copy(
                update={"aliases": _without(concepts[src].aliases, s.keys)}
            )
        if normalize_label(s.label) not in existing:
            todo.append((s, concepts[src].id if src is not None else ""))
    return file.model_copy(update={"concepts": concepts}), todo


def add_concepts(file: ConceptGraphFile, new: Sequence[Concept]) -> ConceptGraphFile:
    return file.model_copy(update={"concepts": [*file.concepts, *new]})


def patch_remove_aliases(file: ConceptGraphFile, overrides: Overrides) -> ConceptGraphFile:
    """Strip listed aliases from their concepts (a missing concept is an error: a stale entry)."""
    concepts = list(file.concepts)
    by_label = {normalize_label(c.label): i for i, c in enumerate(concepts)}
    for r in overrides.remove_alias:
        i = by_label.get(normalize_label(r.label))
        if i is None:
            raise ValueError(f"remove_alias: no concept labelled {r.label!r}")
        keys = {normalize_label(a) for a in r.aliases}
        kept = _without(concepts[i].aliases, keys)
        concepts[i] = concepts[i].model_copy(update={"aliases": kept})
    return file.model_copy(update={"concepts": concepts})


def pending_adds(file: ConceptGraphFile, overrides: Overrides) -> list[AddConcept]:
    """`add` entries not in the graph yet (by normalised label): re-running is a no-op."""
    have = {normalize_label(c.label) for c in file.concepts}
    return [a for a in overrides.add if normalize_label(a.label) not in have]


def patch_adds(
    file: ConceptGraphFile,
    adds: Sequence[AddConcept],
    vectors: dict[str, list[float]],
    zipf: Callable[[str], float],
    new_id: Callable[[str, set[str]], str],
) -> tuple[ConceptGraphFile, list[Concept]]:
    """Add hand-written concepts. `vectors` holds each label's embedding; prerequisites are
    existing labels, resolved to ids (an unknown one is an error)."""
    by_label = {normalize_label(c.label): c.id for c in file.concepts}
    taken = {c.id for c in file.concepts}
    added: list[Concept] = []
    for a in adds:
        prereqs = []
        for label in a.prerequisites:
            pid = by_label.get(normalize_label(label))
            if pid is None:
                raise ValueError(f"add {a.label!r}: unknown prerequisite {label!r}")
            prereqs.append(pid)
        cid = new_id(a.label, taken)
        taken.add(cid)
        added.append(
            Concept(
                id=cid,
                label=a.label,
                aliases=a.aliases,
                domain=a.domain,
                definition=a.definition,
                base_difficulty=difficulty(a.specialization, zipf(a.label)),
                prerequisites=prereqs,
                kind=a.kind,
                jurisdiction=a.jurisdiction,
                embedding=[round(float(x), 4) for x in vectors[a.label]],
            )
        )
        by_label[normalize_label(a.label)] = cid
    return add_concepts(file, added), added
