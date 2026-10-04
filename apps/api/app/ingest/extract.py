"""HTML → title + paragraphs (trafilatura); paragraph ids and offsets for both input shapes."""

import re
from dataclasses import dataclass

import trafilatura

MIN_PARAGRAPH_CHARS = 40
MAX_PARAGRAPHS = 200
MAX_ARTICLE_CHARS = 150_000  # keeps contents/{id} well under Firestore's 1 MiB doc limit
PARAGRAPH_SEPARATOR = "\n\n"

_WS = re.compile(r"\s+")


@dataclass(frozen=True)
class Extracted:
    title: str
    site: str
    paragraphs: list[str]


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
    return Extracted(title, site.strip(), clean_paragraphs(lines))


def build_paragraphs(texts: list[str]) -> list[Paragraph]:
    """Ids p0..pn in document order: the same text always gets the same ids."""
    paragraphs: list[Paragraph] = []
    offset = 0
    for i, text in enumerate(texts):
        paragraphs.append(Paragraph(f"p{i}", text, offset))
        offset += len(text) + len(PARAGRAPH_SEPARATOR)
    return paragraphs
