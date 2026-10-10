"""Shape of the global concept graph file, gs://<bucket>/concepts.json (DESIGN §2)."""

from typing import Literal, get_args

from pydantic import BaseModel, Field

from app.graph.taxonomy import DOMAIN_IDS

Domain = Literal[
    "economics",
    "finance",
    "business",
    "policy",
    "politics",
    "law",
    "technology",
    "science",
    "health",
    "environment",
    "sports",
    "culture",
    "education",
    "society",
]
DOMAINS: tuple[Domain, ...] = get_args(Domain)
assert DOMAINS == DOMAIN_IDS, "Domain must list the taxonomy in order"


class Concept(BaseModel):
    id: str = Field(pattern=r"^c_[a-z0-9_]+$")
    label: str
    aliases: list[str] = Field(default_factory=list)
    wikidata: str | None = Field(default=None, pattern=r"^Q\d+$")
    domain: Domain
    definition: str
    base_difficulty: float = Field(ge=-2, le=2)
    prerequisites: list[str] = Field(default_factory=list, max_length=3)
    # Distinct near-duplicate doc groups mentioning the concept (DESIGN §2); picks a domain's
    # core concepts (§15.3) and seeds an empty knowledge map. 0 in graphs built before M3 and for
    # glossary seeds and grown concepts.
    doc_freq: int = Field(default=0, ge=0)
    # concept_define kind (app/graph/build.py KINDS), stored since M2.2 so kind rules (merge
    # refusal, jurisdiction) work at serving time. None only in graphs built before M2.2.
    kind: str | None = None
    # ISO 3166-1 alpha-2 country code, "EU", or "global" (roles, institutions, laws, taxes and
    # schemes link only within their jurisdiction; M2.2).
    jurisdiction: str = Field(default="global", pattern=r"^([A-Z]{2}|global)$")
    embedding: list[float]


class ConceptGraphFile(BaseModel):
    version: str
    domains: list[Domain] = Field(default_factory=lambda: list(DOMAINS))
    concepts: list[Concept]
