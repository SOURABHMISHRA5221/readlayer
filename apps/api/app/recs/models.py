"""Shapes shared by the recommender: normalized web results and ranked candidates."""

from typing import Literal

from pydantic import BaseModel, Field

Format = Literal["article", "video", "podcast"]
FORMATS: tuple[Format, ...] = ("article", "video", "podcast")

Relation = Literal["same_story", "primer", "deeper", "angle", "explainer", "feed"]
# Up next's relations; "feed" (M7.5 For you) is served and evented but never ranks Up next.
RELATIONS: tuple[Relation, ...] = ("same_story", "primer", "deeper", "angle", "explainer")


class WebResult(BaseModel):
    """Every provider's results are normalized to this before caching or ranking."""

    url: str
    title: str
    source: str
    format: Format
    duration_or_read_time: int | None = Field(
        default=None, description="seconds: video/podcast length, or estimated reading time"
    )
    snippet: str = ""
    thumbnail: str | None = None
    published_at: str | None = None
