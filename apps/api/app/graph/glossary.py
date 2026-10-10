"""Deterministic parser for Wikipedia glossary pages (M2.2 seeding, decision 34). Pure.

Four layouts cover the glossaries we seed from (probed 2026-10-10):
1. `dl.glossary > dt / dd` (the {{glossary}} template);
2. plain `dl > dt / dd`;
3. `ul > li` that starts with a bold term followed by a dash or colon;
4. a heading per term (h3/h4) followed by its paragraph, used only when a page has many such
   headings and few entries of the other layouts.

The definition's first sentence is kept as a context snippet only, to tell `concept_define`
which sense is meant; it is never stored as our definition and never leaves the build cache.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass

from lxml import html as lxml_html

from app.graph.build import normalize_label

SNIPPET_CHARS = 220
MAX_TERM_CHARS = 80
HEADING_LAYOUT_MIN = 20  # headings needed before layout 4 is trusted
SKIP_SECTIONS = frozenset(
    {"see also", "references", "notes", "external links", "further reading", "bibliography",
     "sources", "citations", "footnotes", "contents", "works cited"}
)  # fmt: skip
_DROP_XPATH = (
    ".//sup[contains(@class,'reference')] | .//*[contains(@class,'navbox')]"
    " | .//*[contains(@class,'reflist')] | .//*[contains(@class,'hatnote')]"
    " | .//*[contains(@class,'mw-editsection')] | .//*[contains(@class,'sidebar')]"
    " | .//*[contains(@class,'portalbox')] | .//*[contains(@class,'toc')] | .//style"
    " | .//*[contains(@class,'noprint')] | .//*[contains(@class,'shortdescription')]"
)
_FOOTNOTE = re.compile(r"\[(?:\d+|[a-z]|note \d+|citation needed)\]", re.I)
_SPACE = re.compile(r"\s+")
_PAREN = re.compile(r"\s*\(([^)]*)\)")
_SEPARATOR = re.compile(r"^\s*[–—:\-]\s*")
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\"'])")


@dataclass(frozen=True)
class GlossaryEntry:
    label: str
    aliases: tuple[str, ...]
    snippet: str


def _text(el) -> str:
    return _SPACE.sub(" ", _FOOTNOTE.sub("", el.text_content())).strip()


def _first_sentence(text: str) -> str:
    text = _SPACE.sub(" ", text).strip()
    return _SENTENCE.split(text, maxsplit=1)[0][:SNIPPET_CHARS]


def clean_term(raw: str) -> tuple[str, tuple[str, ...]] | None:
    """`abstract data type (ADT)` → ("Abstract data type", ("ADT",)). None if not a term."""
    raw = _FOOTNOTE.sub("", raw).strip().strip(":;,.–—-").strip()
    aliases = tuple(
        a.strip() for a in _PAREN.findall(raw) if 1 < len(a.strip()) <= 12 and " " not in a.strip()
    )
    label = _PAREN.sub("", raw).strip()
    label = label.split(" or ")[0].split(", ")[0].strip().strip('"“”')
    if (
        not label
        or len(label) > MAX_TERM_CHARS
        or len(label) < 2
        or not any(c.isalpha() for c in label)
    ):
        return None
    if label[0].islower():
        label = label[0].upper() + label[1:]
    return label, aliases


def _roots(tree) -> list:
    """The article body, minus references, navigation and See also / References sections."""
    roots = tree.xpath("//div[contains(@class,'mw-parser-output')]") or [tree]
    for root in roots:
        for bad in root.xpath(_DROP_XPATH):
            bad.getparent().remove(bad)
        for el in root.xpath(".//dl | .//ul | .//h3 | .//h4"):
            if el.getparent() is not None and _skipped_section(el):
                el.getparent().remove(el)
    return roots


def _skipped_section(el) -> bool:
    """True when the nearest preceding h2 names a section we skip (See also, References…)."""
    heading = next(iter(el.xpath("preceding::h2[1]")), None)
    return heading is not None and _text(heading).casefold() in SKIP_SECTIONS


def _from_dl(root) -> Iterator[tuple[str, str]]:
    for dl in root.iter("dl"):
        term = None
        for child in dl:
            if child.tag == "dt":
                term = _text(child)
            elif child.tag == "dd" and term:
                yield term, _text(child)
                term = None


def _from_lists(root) -> Iterator[tuple[str, str]]:
    for li in root.xpath(".//ul/li"):
        first = next((c for c in li if isinstance(c.tag, str)), None)
        if first is None or first.tag not in ("b", "strong") or (li.text or "").strip():
            continue
        term = _text(first)
        rest = (first.tail or "") + "".join(
            (_text(c) if isinstance(c.tag, str) else "") + (c.tail or "")  # comments: tail only
            for c in first.itersiblings()
        )
        if _SEPARATOR.match(rest):
            yield term, _SEPARATOR.sub("", rest, count=1)


def _from_headings(root) -> Iterator[tuple[str, str]]:
    for h in root.xpath(".//h3 | .//h4"):
        para = next(iter(h.xpath("following::p[1]")), None)
        if para is not None:
            yield _text(h), _text(para)


def parse(page: str | bytes) -> list[GlossaryEntry]:
    tree = lxml_html.fromstring(page)
    pairs: list[tuple[str, str]] = []
    for root in _roots(tree):
        listed = [*_from_dl(root), *_from_lists(root)]
        headings = list(_from_headings(root))
        if len(listed) < HEADING_LAYOUT_MIN <= len(headings):
            listed += headings
        pairs += listed
    out: list[GlossaryEntry] = []
    seen: set[str] = set()
    for term, definition in pairs:
        cleaned = clean_term(term)
        if cleaned is None:
            continue
        label, aliases = cleaned
        key = normalize_label(label)
        if not key or key in seen or key in SKIP_SECTIONS:
            continue
        seen.add(key)
        out.append(GlossaryEntry(label, aliases, _first_sentence(definition)))
    return out
