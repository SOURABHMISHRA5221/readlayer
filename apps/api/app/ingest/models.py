"""Stored shape of a demand profile, Firestore `contents/{url_hash}` (DESIGN §3), and of an
article fetched but not yet analysed, `pending_contents/{url_hash}` (two-phase "Open here")."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

DemandType = Literal["concept", "term", "context"]
USER_INGESTED = "user_ingested"
Source = Literal["fetch", "extension", "user_ingested"]


class Anchor(BaseModel):
    """W3C TextQuoteSelector plus article-level char offsets as a hint."""

    exact: str
    prefix: str
    suffix: str
    start: int
    end: int


class Demand(BaseModel):
    id: str
    paragraph_id: str
    anchor: Anchor
    type: DemandType
    label: str  # model's canonical name; M2 links it to target_id
    target_id: str | None = None
    salience: float = Field(ge=0, le=1)
    explained_in_text: bool
    zipf: float
    # True when target_id is a concept grown from this very article (M2.2): evals keep these out
    # of the frozen-graph headline (decision 34).
    grown: bool = False


class StoredParagraph(BaseModel):
    id: str
    text: str
    structure: float = Field(ge=0, le=1)


class LLMCall(BaseModel):
    task: str
    model: str
    prompt_version: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    fell_back: bool


class ContentDoc(BaseModel):
    content_id: str
    url: str
    final_url: str
    title: str
    site: str
    # user_ingested: opened by a reader from a web recommendation ("Open here"). Never corpus
    # or held-out data: build_concepts and eval_heldout skip it even if its URL is listed.
    source: Source
    fetched_at: str
    # Publisher metadata (description = standfirst). None when the page declares none, or for
    # docs ingested before it was stored and not yet backfilled (scripts/backfill_metadata.py).
    description: str | None = None
    author: str | None = None
    published: str | None = None
    image: str | None = None  # publisher's og:image URL; the UI hotlinks it with no referrer
    paragraphs: list[StoredParagraph]
    demands: list[Demand]
    demands_dropped: int
    llm_calls: list[LLMCall]


class PendingParagraph(BaseModel):
    id: str
    text: str


class PendingDoc(BaseModel):
    """Phase 1 of an ingest: the article as fetched and extracted, before demand extraction.

    Shared content, like `contents/`: publisher text and metadata only, never a uid or anything
    about the reader who opened it. Paragraph ids and text are final; phase 2 reuses them
    unchanged, so a reader who saw the pending article gets notes anchored to the same text.
    """

    content_id: str
    url: str
    final_url: str
    title: str
    site: str
    source: Source
    fetched_at: str
    description: str | None = None
    author: str | None = None
    published: str | None = None
    image: str | None = None
    paragraphs: list[PendingParagraph]
    # Concept-growth slots reserved for this article in phase 1 (M2.2); no uid is stored.
    grow_slots: int = Field(default=0, ge=0)
    # Analyses that ran and failed (not budget refusals or a busy lease); capped.
    attempts: int = 0
    lease_until: datetime | None = None
    expire_at: datetime  # Firestore TTL field: abandoned pending docs go after a day
