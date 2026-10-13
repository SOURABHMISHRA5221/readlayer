"""Transcript windows → timed paragraphs (Media plan §D "Assembly"). Pure: no I/O.

A recording is transcribed in windows of about ten minutes. Each window's model output is
checked here (times inside the window, no loops, a believable speaking rate), then the windows
are joined into one list of paragraphs with start times. Words are never changed, dropped or
reordered: only whitespace is collapsed and paragraphs are grouped.
"""

import re
from collections import Counter
from dataclasses import dataclass

from pydantic import BaseModel, Field

from app.ingest.extract import MAX_ARTICLE_CHARS, MAX_PARAGRAPHS, PARAGRAPH_SEPARATOR
from app.llm import InvalidTranscript

WINDOW_S = 600
MIN_LAST_WINDOW_S = 60  # a shorter tail joins the window before it
TIME_SLACK_S = 5
MAX_WORDS_PER_MIN = 300
REPEAT_MIN_CHARS = 30  # a paragraph this long seen three times means the model looped
REPEAT_LIMIT = 3
MIN_PARAGRAPH_WORDS = 25
MIN_TRANSCRIPT_WORDS = 80  # the article rule (ingest MIN_ARTICLE_WORDS)

CLOCK_PATTERN = r"^(\d{1,2}:)?\d{1,3}:\d{2}$"
_WS = re.compile(r"\s+")
_CLOSING = (".", "!", "?", "…", '"', "”", "'", "’", ")")


class TranscriptParagraph(BaseModel):
    start: str = Field(pattern=CLOCK_PATTERN)
    text: str


class TranscriptWindow(BaseModel):
    """The `transcribe` task's output schema for one window."""

    language: str
    paragraphs: list[TranscriptParagraph]


@dataclass(frozen=True)
class Window:
    index: int
    start_s: int
    end_s: int

    @property
    def length_s(self) -> int:
        return self.end_s - self.start_s


@dataclass(frozen=True)
class TimedParagraph:
    start_s: int
    text: str


@dataclass(frozen=True)
class WindowText:
    """One checked window: its language and paragraphs with absolute start times."""

    language: str
    paragraphs: tuple[TimedParagraph, ...]

    @property
    def words(self) -> int:
        return sum(len(p.text.split()) for p in self.paragraphs)


class TranscriptRefused(Exception):
    """The recording can't be shown: `code` is the API's refusal code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def plan_windows(duration_s: int, size_s: int = WINDOW_S) -> list[Window]:
    """Back-to-back windows covering [0, duration_s); a tail under a minute joins the last."""
    if duration_s <= 0:
        return []
    bounds = list(range(0, duration_s, size_s)) + [duration_s]
    if len(bounds) > 2 and bounds[-1] - bounds[-2] < MIN_LAST_WINDOW_S:
        del bounds[-2]
    return [Window(i, a, b) for i, (a, b) in enumerate(zip(bounds, bounds[1:], strict=False))]


def parse_clock(text: str) -> int:
    """'MM:SS' or 'H:MM:SS' → seconds. Raises ValueError on anything else."""
    if not re.match(CLOCK_PATTERN, text):
        raise ValueError(f"not a clock time: {text!r}")
    total = 0
    for part in text.split(":"):
        total = total * 60 + int(part)
    return total


def check_window(out: TranscriptWindow, window: Window, *, relative_only: bool) -> WindowText:
    """Validate one window's output and put its times on the recording's clock.

    YouTube windows may come back with times counted from the recording's start (absolute) or
    from the window's start (relative); audio pieces are always relative. Raises
    InvalidTranscript (the caller asks again once, then the item fails).
    """
    paragraphs = [(parse_clock(p.start), _WS.sub(" ", p.text).strip()) for p in out.paragraphs]
    paragraphs = [(t, text) for t, text in paragraphs if text]
    times = [t for t, _ in paragraphs]
    if times and not relative_only and _fits(times, window.start_s, window.end_s):
        shift = 0
    elif times and _fits(times, 0, window.length_s):
        shift = window.start_s
    elif times:
        raise InvalidTranscript(f"times outside window {window.index}")
    else:
        shift = 0
    _check_loops([text for _, text in paragraphs])
    words = sum(len(text.split()) for _, text in paragraphs)
    if words > MAX_WORDS_PER_MIN * window.length_s / 60:
        raise InvalidTranscript(f"{words} words in {window.length_s} s")
    timed: list[TimedParagraph] = []
    floor = window.start_s
    for t, text in paragraphs:
        floor = max(floor, min(t + shift, window.end_s))  # never before the paragraph above
        timed.append(TimedParagraph(floor, text))
    return WindowText(out.language.strip(), tuple(timed))


def _fits(times: list[int], low: int, high: int) -> bool:
    return all(low - TIME_SLACK_S <= t <= high + TIME_SLACK_S for t in times)


def _check_loops(texts: list[str]) -> None:
    counts = Counter(t.casefold() for t in texts if len(t) > REPEAT_MIN_CHARS)
    if counts and max(counts.values()) >= REPEAT_LIMIT:
        raise InvalidTranscript("a paragraph repeats: the model looped")


def main_language(windows: list[WindowText]) -> str:
    """The language spoken most, counted in words over all windows ('' when silent)."""
    words: Counter[str] = Counter()
    for w in windows:
        words[w.language.lower()] += w.words
    words.pop("", None)
    return words.most_common(1)[0][0] if words else ""


def is_english(language: str) -> bool:
    return language.lower().split("-")[0] == "en"


def assemble(windows: list[WindowText]) -> list[TimedParagraph]:
    """Join checked windows (in order) into the transcript's paragraphs.

    Raises TranscriptRefused: `not_english`, `no_speech` (under 80 words) or `too_long`.
    """
    if sum(w.words for w in windows) < MIN_TRANSCRIPT_WORDS:
        raise TranscriptRefused("no_speech")
    if not is_english(main_language(windows)):
        raise TranscriptRefused("not_english")
    out: list[TimedParagraph] = []
    for window in windows:
        merged = _merge_short(list(window.paragraphs))
        if out and merged and _continues(out[-1].text, merged[0].text):
            out[-1] = _join(out[-1], merged[0])
            merged = merged[1:]
        out.extend(merged)
    if len(out) > 1 and _word_count(out[-1]) < MIN_PARAGRAPH_WORDS:
        out[-2:] = [_join(out[-2], out[-1])]
    while len(out) > MAX_PARAGRAPHS:
        i = min(range(len(out) - 1), key=lambda k: len(out[k].text) + len(out[k + 1].text))
        out[i : i + 2] = [_join(out[i], out[i + 1])]
    total = sum(len(p.text) for p in out) + len(PARAGRAPH_SEPARATOR) * max(len(out) - 1, 0)
    if total > MAX_ARTICLE_CHARS:
        raise TranscriptRefused("too_long")
    return out


def _merge_short(paragraphs: list[TimedParagraph]) -> list[TimedParagraph]:
    """A paragraph under MIN_PARAGRAPH_WORDS joins the next one in the same window."""
    out: list[TimedParagraph] = []
    carry: TimedParagraph | None = None
    for p in paragraphs:
        p = _join(carry, p) if carry else p
        carry = None
        if _word_count(p) < MIN_PARAGRAPH_WORDS:
            carry = p
        else:
            out.append(p)
    if carry:
        out.append(carry)
    return out


def _continues(previous: str, following: str) -> bool:
    """A sentence cut by a window boundary: no closing punctuation, then a lower-case start."""
    return not previous.rstrip().endswith(_CLOSING) and following[:1].islower()


def _join(a: TimedParagraph, b: TimedParagraph) -> TimedParagraph:
    return TimedParagraph(a.start_s, f"{a.text} {b.text}")


def _word_count(p: TimedParagraph) -> int:
    return len(p.text.split())
