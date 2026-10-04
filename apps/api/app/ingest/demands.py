"""Demand extraction (DESIGN §3): one LLM pass per chunk, then strict anchor verification.

Anchors whose `exact` text does not occur verbatim in their paragraph are dropped, never repaired:
a repaired anchor would point at text the model did not actually analyse.
"""

import logging
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from app import llm
from app.ingest.extract import Paragraph
from app.ingest.features import zipf
from app.ingest.models import Anchor, Demand, LLMCall

log = logging.getLogger("app.ingest.demands")

TASK = "extract_demands"
CHUNK_CHARS = 24_000  # ~6k tokens (DESIGN §3)
CONTEXT_CHARS = 32  # prefix/suffix length for TextQuoteSelector anchors


class DemandItem(BaseModel):
    exact: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=120)
    type: Literal["concept", "term", "context"]
    salience: float = Field(ge=0, le=1)
    explained_in_text: bool


class ParagraphDemands(BaseModel):
    paragraph_id: str
    structurally_dense: bool
    items: list[DemandItem] = Field(default_factory=list, max_length=12)


class DemandExtraction(BaseModel):
    paragraphs: list[ParagraphDemands]


@dataclass(frozen=True)
class DemandResult:
    demands: list[Demand]
    dense: dict[str, bool]  # paragraph id -> LLM structure flag
    dropped: int
    calls: list[LLMCall]


def chunk(paragraphs: list[Paragraph], max_chars: int | None = None) -> list[list[Paragraph]]:
    max_chars = max_chars or CHUNK_CHARS
    chunks: list[list[Paragraph]] = []
    current: list[Paragraph] = []
    size = 0
    for p in paragraphs:
        if current and size + len(p.text) > max_chars:
            chunks.append(current)
            current, size = [], 0
        current.append(p)
        size += len(p.text)
    if current:
        chunks.append(current)
    return chunks


def render_paragraphs(paragraphs: list[Paragraph]) -> str:
    return "\n\n".join(f"[{p.id}] {p.text}" for p in paragraphs)


def verify_anchor(paragraph: Paragraph, exact: str) -> Anchor | None:
    """Locate `exact` verbatim in the paragraph; context comes from the real text."""
    pos = paragraph.text.find(exact)
    if not exact.strip() or pos < 0:
        return None
    end = pos + len(exact)
    return Anchor(
        exact=exact,
        prefix=paragraph.text[max(0, pos - CONTEXT_CHARS) : pos],
        suffix=paragraph.text[end : end + CONTEXT_CHARS],
        start=paragraph.start + pos,
        end=paragraph.start + end,
    )


async def extract_demands(paragraphs: list[Paragraph]) -> DemandResult:
    """Raises llm.BudgetExceeded / LLMUnavailable / LLMRejected unchanged."""
    by_id = {p.id: p for p in paragraphs}
    demands: list[Demand] = []
    dense: dict[str, bool] = {}
    calls: list[LLMCall] = []
    seen: set[tuple[str, str]] = set()
    dropped = 0
    for part in chunk(paragraphs):
        result = await llm.run_with_meta(
            TASK,
            DemandExtraction,
            {"paragraph_count": len(part), "paragraphs": render_paragraphs(part)},
        )
        m = result.meta
        calls.append(
            LLMCall(
                task=m.task,
                model=m.model,
                prompt_version=m.prompt_version,
                tokens_in=m.tokens_in,
                tokens_out=m.tokens_out,
                cost_usd=m.cost_usd,
                fell_back=m.fell_back,
            )
        )
        allowed = {p.id for p in part}
        for pd in result.output.paragraphs:
            if pd.paragraph_id not in allowed:
                dropped += len(pd.items)
                continue
            dense[pd.paragraph_id] = pd.structurally_dense
            for item in pd.items:
                key = (pd.paragraph_id, item.exact)
                anchor = verify_anchor(by_id[pd.paragraph_id], item.exact)
                if anchor is None:
                    dropped += 1
                    continue
                if key in seen:
                    continue
                seen.add(key)
                demands.append(
                    Demand(
                        id=f"d{len(demands)}",
                        paragraph_id=pd.paragraph_id,
                        anchor=anchor,
                        type=item.type,
                        label=item.label,
                        salience=item.salience,
                        explained_in_text=item.explained_in_text,
                        zipf=zipf(item.exact),
                    )
                )
    if dropped:
        log.info("dropped unverifiable anchors", extra={"dropped": dropped, "kept": len(demands)})
    return DemandResult(demands, dense, dropped, calls)
