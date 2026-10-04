"""HTML → title + paragraphs (trafilatura); paragraph ids and offsets for both input shapes."""

import re
from dataclasses import dataclass

import trafilatura

MIN_PARAGRAPH_CHARS = 40
MAX_PARAGRAPHS = 200
MAX_ARTICLE_CHARS = 150_000  # keeps contents/{id} well under Firestore's 1 MiB doc limit
MAX_DESCRIPTION_CHARS = 500
MAX_AUTHOR_CHARS = 160
MAX_IMAGE_URL_CHARS = 1000
PARAGRAPH_SEPARATOR = "\n\n"

_WS = re.compile(r"\s+")


@dataclass(frozen=True)
class Metadata:
    """The publisher's own metadata, shown as-is (never generated or rewritten)."""

    description: str | None = None
    author: str | None = None
    published: str | None = None  # ISO date as the page declares it
    image: str | None = None  # the page's own lead image (og:image), absolute http(s) URL


@dataclass(frozen=True)
class Extracted:
    title: str
    site: str
    paragraphs: list[str]
    metadata: Metadata = Metadata()


@dataclass(frozen=True)
class Paragraph:
    id: str
    text: str
    start: int  # char offset in the article text (paragraphs joined by PARAGRAPH_SEPARATOR)


def clean_paragraphs(texts: list[str]) -> list[str]:
    """Collapse whitespace, drop fragments, cap size. Used for fetched and submitted text."""
    out: list[str] = []
    total = 0
    for raw in texts:
        text = _WS.sub(" ", raw).strip()
        if len(text) < MIN_PARAGRAPH_CHARS:
            continue
        total += len(text) + len(PARAGRAPH_SEPARATOR)
        if len(out) >= MAX_PARAGRAPHS or total > MAX_ARTICLE_CHARS:
            break
        out.append(text)
    return out


def extract(html: str | bytes, url: str) -> Extracted:
    text = trafilatura.extract(
        html,
        url=url,
        output_format="txt",
        include_comments=False,
        include_tables=False,
        include_links=False,
        favor_precision=True,
    )
    meta = trafilatura.extract_metadata(html, default_url=url)
    title = (meta.title if meta else None) or ""
    site = (meta.sitename or meta.hostname if meta else None) or ""
    title = title.strip()
    lines = [line for line in (text or "").splitlines() if line.strip() != title]  # headline echo
    return Extracted(title, site.strip(), clean_paragraphs(lines), _metadata(meta))


def extract_metadata(html: str | bytes, url: str) -> Metadata:
    """Metadata only, for backfilling docs ingested before it was stored."""
    return _metadata(trafilatura.extract_metadata(html, default_url=url))


def _metadata(meta: object | None) -> Metadata:
    if meta is None:
        return Metadata()
    return Metadata(
        description=_clip(getattr(meta, "description", None), MAX_DESCRIPTION_CHARS),
        author=_clip(getattr(meta, "author", None), MAX_AUTHOR_CHARS),
        published=_clip(getattr(meta, "date", None), 32),
        image=_image_url(getattr(meta, "image", None)),
    )


def _image_url(value: str | None) -> str | None:
    """Only absolute http(s) URLs; anything else (data:, javascript:, relative) is dropped."""
    url = (value or "").strip()
    if len(url) > MAX_IMAGE_URL_CHARS or not url.lower().startswith(("https://", "http://")):
        return None
    return url


def _clip(value: str | None, limit: int) -> str | None:
    text = _WS.sub(" ", value or "").strip()
    return text[:limit] or None


def build_paragraphs(texts: list[str]) -> list[Paragraph]:
    """Ids p0..pn in document order: the same text always gets the same ids."""
    paragraphs: list[Paragraph] = []
    offset = 0
    for i, text in enumerate(texts):
        paragraphs.append(Paragraph(f"p{i}", text, offset))
        offset += len(text) + len(PARAGRAPH_SEPARATOR)
    return paragraphs
