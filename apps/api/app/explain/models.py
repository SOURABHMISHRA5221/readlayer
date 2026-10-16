"""Schemas for explanations (DESIGN §7): the generator's output and the judge's verdict."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.reader.frames import Frame

Mode = Literal["span", "paragraph"]


class Explanation(BaseModel):
    """A two-part card as served (and as the eval cases hold it). Each part is generated and
    verified on its own (DESIGN §7) and shown only after its verifier passes it."""

    model_config = ConfigDict(extra="forbid")

    background: str = Field(min_length=1, max_length=1000)
    author_says: str = Field(min_length=1, max_length=1500)
    analogy_domain: Frame | None = None


class Card(BaseModel):
    """The card as served: the restatement is always verified when present; the Background
    may be missing (rejected) and the client then keeps the definition in its panel."""

    background: str | None
    author_says: str | None
    analogy_domain: Frame | None = None


class Restatement(BaseModel):
    """What `restate` returns: what the author says, for every reader alike."""

    model_config = ConfigDict(extra="forbid")

    author_says: str = Field(min_length=1, max_length=1500)


class BackgroundDraft(BaseModel):
    """What `explain` returns: the reader's Background, at their level and in their frame."""

    model_config = ConfigDict(extra="forbid")

    background: str = Field(min_length=1, max_length=1000)
    analogy_domain: Frame | None = None


class ClaimVerdict(BaseModel):
    claim: str = Field(max_length=600)
    verdict: Literal["entailed", "not_entailed", "contradicted"]
    reason: str = Field(max_length=600)


class Verdict(BaseModel):
    """What `verify` returns: one verdict per atomic claim of `author_says`."""

    model_config = ConfigDict(extra="forbid")

    claims: list[ClaimVerdict] = Field(min_length=1, max_length=20)

    @property
    def passed(self) -> bool:
        return all(c.verdict == "entailed" for c in self.claims)

    def reasons(self) -> list[str]:
        return [
            f"judge_{c.verdict}: {c.claim} ({c.reason})"
            for c in self.claims
            if c.verdict != "entailed"
        ]


class BackgroundVerdict(BaseModel):
    """What `verify_background` returns: whether the Background contradicts the source or makes
    claims about this article (it must be general knowledge)."""

    model_config = ConfigDict(extra="forbid")

    background_issue: Literal["none", "contradicts", "article_claim"]
    background_reason: str = Field(default="", max_length=600)

    @property
    def passed(self) -> bool:
        return self.background_issue == "none"

    def reasons(self) -> list[str]:
        if self.background_issue == "none":
            return []
        return [f"judge_background_{self.background_issue}: {self.background_reason}"]
