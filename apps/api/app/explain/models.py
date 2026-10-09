"""Schemas for explanations (DESIGN §7): the generator's output and the judge's verdict."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.reader.state import ThinksIn

Mode = Literal["span", "paragraph"]


class Explanation(BaseModel):
    """What `explain` returns. Shown only after the verifier passes it."""

    model_config = ConfigDict(extra="forbid")

    background: str = Field(min_length=1, max_length=1000)
    author_says: str = Field(min_length=1, max_length=1500)
    analogy_domain: ThinksIn | None = None


class ClaimVerdict(BaseModel):
    claim: str = Field(max_length=600)
    verdict: Literal["entailed", "not_entailed", "contradicted"]
    reason: str = Field(max_length=600)


class Verdict(BaseModel):
    """What `verify` returns: one verdict per atomic claim of `author_says`, and whether the
    background contradicts the source or makes claims about this article."""

    model_config = ConfigDict(extra="forbid")

    claims: list[ClaimVerdict] = Field(min_length=1, max_length=20)
    background_issue: Literal["none", "contradicts", "article_claim"]
    background_reason: str = Field(default="", max_length=600)

    @property
    def passed(self) -> bool:
        return self.background_issue == "none" and all(c.verdict == "entailed" for c in self.claims)

    def reasons(self) -> list[str]:
        out = [
            f"judge_{c.verdict}: {c.claim} ({c.reason})"
            for c in self.claims
            if c.verdict != "entailed"
        ]
        if self.background_issue != "none":
            out.append(f"judge_background_{self.background_issue}: {self.background_reason}")
        return out
