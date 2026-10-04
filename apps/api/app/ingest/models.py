"""Stored shape of a demand profile, Firestore `contents/{url_hash}` (DESIGN §3)."""

from typing import Literal

from pydantic import BaseModel, Field

DemandType = Literal["concept", "term", "context"]
USER_INGESTED = "user_ingested"


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
    source: Literal["fetch", "extension", "user_ingested"]
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
