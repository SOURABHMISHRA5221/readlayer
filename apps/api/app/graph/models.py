"""Shape of the global concept graph file, gs://<bucket>/concepts.json (DESIGN §2)."""

from typing import Literal

from pydantic import BaseModel, Field

Domain = Literal["economics", "finance", "business", "policy"]
DOMAINS: tuple[Domain, ...] = ("economics", "finance", "business", "policy")


class Concept(BaseModel):
    id: str = Field(pattern=r"^c_[a-z0-9_]+$")
    label: str
    aliases: list[str] = Field(default_factory=list)
    wikidata: str | None = Field(default=None, pattern=r"^Q\d+$")
    domain: Domain
    definition: str
    base_difficulty: float = Field(ge=-2, le=2)
    prerequisites: list[str] = Field(default_factory=list, max_length=3)
    embedding: list[float]


class ConceptGraphFile(BaseModel):
    version: str
    domains: list[Domain] = Field(default_factory=lambda: list(DOMAINS))
    concepts: list[Concept]
