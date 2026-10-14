"""Stored shape of a demand profile, Firestore `contents/{url_hash}` (DESIGN §3), and of an
article fetched but not yet analysed, `pending_contents/{url_hash}` (two-phase "Open here")."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

DemandType = Literal["concept", "term", "context"]
USER_INGESTED = "user_ingested"
Source = Literal["fetch", "extension", "user_ingested"]
# Pages a reader brought in ("Open here", Read any link, the extension). Shared so other readers
# of the same URL reuse them, but not public library content: the library and Up next show them
# only to readers who brought them in (`users/{uid}/ingested`, M7.5). Same name as the M8 plan.
NOT_CORPUS: frozenset[str] = frozenset({USER_INGESTED, "extension"})


def is_corpus(doc: "ContentDoc") -> bool:
    return doc.source not in NOT_CORPUS


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
    start_s: int | None = None  # a transcript paragraph's start in the recording (DESIGN §21)


MediaKind = Literal["youtube", "audio"]
Stage = Literal["transcribe", "analyse"]


class TranscriptRecord(BaseModel):
    """How a transcript was made: shown nowhere, kept for cost and prompt-version audits."""

    model: str
    prompt_version: str
    windows: int
    cost_usd: float  # every billed call for this recording, failed attempts included
    made_at: str
    tokens_in: int = 0
    tokens_out: int = 0


class Media(BaseModel):
    """A recording read as a transcript (decision 54). Content only, no uid."""

    kind: MediaKind
    video_id: str | None = None
    audio_url: str | None = None  # the publisher's file; played from there, never re-hosted
    duration_s: int
    # The spoken language when the source declares it (YouTube defaultAudioLanguage); None =
    # unknown, so window 1 runs alone first (plan R8).
    language: str | None = None
    transcript: TranscriptRecord | None = None


class WindowParagraph(BaseModel):
    start_s: int
    text: str


class WindowRecord(BaseModel):
    """One transcribed window, stored as it finishes so a retry never pays for it again."""

    language: str
    paragraphs: list[WindowParagraph]


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
    media: Media | None = None
    # Concept growth on a stored page (M9 part 1, DESIGN §2): `grow_pending` true when the caps cut
    # growth short (None: stored before M9; see growth.needs_growth), `grow_tried` the normalised
    # labels already tried (never tried again). A reopen grows it under a claim: `grow_token` and
    # `growing_until` (a random token, no reader data).
    grow_pending: bool | None = None
    grow_tried: list[str] = Field(default_factory=list)
    grow_token: str | None = None
    growing_until: datetime | None = None


class PendingParagraph(BaseModel):
    id: str
    text: str
    start_s: int | None = None


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
    # Media (decision 54): a recording starts at stage "transcribe" with no paragraphs. Its own
    # attempt counter (any billed run counts, plan R2); a random token per lease so a run that
    # lost its lease can't write (R1); windows stored as they finish; every billed call's cost.
    media: Media | None = None
    stage: Stage = "analyse"
    refused: str | None = None  # a refusal code found while transcribing; kept until expiry
    transcribe_attempts: int = 0
    lease_token: str | None = None
    windows: dict[str, WindowRecord] = Field(default_factory=dict)
    # "<frames>:<bytes>" of the audio the saved windows came from: a retry that fetches other
    # bytes (dynamically inserted ads) drops them and starts over (5R3).
    audio_fingerprint: str | None = None
    transcribe_cost_usd: float = 0.0
