"""MP3 frames → exact duration and one piece per transcript window (Media plan §C, Round 5
5.4, 5R1, 5R3, 5R4). Pure: no I/O.

A podcast is sent to the model inline, about ten minutes at a time. The bytes are walked frame
by frame (MPEG 1, 2 and 2.5 Layer III; tags at either end skipped; junk between frames skipped
by resyncing), which gives the exact duration. Pieces are cut on time only, at the first frame
at or after each window's start, so piece i is window i whatever the bitrate. Pieces are views
into the fetched bytes, never copies.
"""

import math
from array import array
from bisect import bisect_left
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache

from app.media.refusals import MediaRefused
from app.media.transcript import Window

MAX_PIECE_BYTES = 14_500_000  # row 14's 14.4 MB went through; base64 of 15 MB is the 20 MB limit
MIN_FRAMES_S = 30  # less audio than this isn't a podcast episode we can read
MIN_FRAME_SHARE = 0.9  # of the bytes between the tags; less means it isn't really an MP3

_ID3V2_HEADER = 10
_ID3V1_SIZE = 128
_APE_FOOTER = 32
_APE_HAS_HEADER = 1 << 31

_BITRATES_KBPS = {
    True: (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320),  # MPEG 1
    False: (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160),  # MPEG 2 and 2.5
}
_SAMPLE_RATES = {  # by version bits: MPEG 1, 2, 2.5
    0b11: (44100, 48000, 32000),
    0b10: (22050, 24000, 16000),
    0b00: (11025, 12000, 8000),
}

Buffer = bytes | bytearray


@dataclass(frozen=True)
class FrameHeader:
    bitrate_kbps: int
    sample_rate: int
    samples: int
    length: int  # bytes, header included

    @property
    def seconds(self) -> float:
        return self.samples / self.sample_rate


@dataclass(frozen=True, eq=False)
class Walk:
    """Every frame's offset and start time, from one pass over the bytes."""

    data: Buffer
    offsets: array  # byte offset of each frame
    starts: array  # start time of each frame, seconds
    stop: int  # end of the last whole frame
    duration_s: float

    @property
    def frames(self) -> int:
        return len(self.offsets)

    @property
    def fingerprint(self) -> str:
        """Changes when a retry fetches different bytes (dynamic ads): "<frames>:<bytes>"."""
        return f"{self.frames}:{len(self.data)}"


@dataclass(frozen=True)
class Piece:
    index: int  # the window's index
    start_s: float  # its first frame's start on the recording's clock
    data: memoryview


@lru_cache(maxsize=4096)
def _decode(b1: int, b2: int, b3: int) -> FrameHeader | None:
    if b1 & 0xE0 != 0xE0:
        return None
    version = (b1 >> 3) & 0b11
    if version == 0b01 or (b1 >> 1) & 0b11 != 0b01:  # reserved version; not Layer III
        return None
    bitrate_index, rate_index = b2 >> 4, (b2 >> 2) & 0b11
    if bitrate_index in (0, 15) or rate_index == 3 or b3 & 0b11 == 0b10:
        return None  # free format, bad bitrate, reserved rate, reserved emphasis
    mpeg1 = version == 0b11
    kbps = _BITRATES_KBPS[mpeg1][bitrate_index]
    rate = _SAMPLE_RATES[version][rate_index]
    samples = 1152 if mpeg1 else 576
    length = samples // 8 * kbps * 1000 // rate + ((b2 >> 1) & 1)
    return FrameHeader(kbps, rate, samples, length)


def parse_header(data: Buffer | memoryview, pos: int = 0) -> FrameHeader | None:
    """The Layer III frame header at `pos`, or None."""
    if len(data) - pos < 4 or data[pos] != 0xFF:
        return None
    return _decode(data[pos + 1], data[pos + 2], data[pos + 3])


def id3v2_size(head: Buffer) -> int:
    """Bytes taken by an ID3v2 tag at the start (header and footer included), else 0. Needs
    the first ten bytes; the caller fetches past a tag bigger than what it has (5R1)."""
    if len(head) < _ID3V2_HEADER or bytes(head[:3]) != b"ID3":
        return 0
    size_bytes = head[6:10]
    if any(b & 0x80 for b in size_bytes):
        return 0
    size = 0
    for b in size_bytes:
        size = (size << 7) | b
    footer = _ID3V2_HEADER if head[5] & 0x10 else 0
    return _ID3V2_HEADER + size + footer


def _audio_end(data: Buffer, start: int) -> int:
    """Where the frames end: before an ID3v1 tag and an APEv2 tag, in that order from the end."""
    end = len(data)
    if end - start >= _ID3V1_SIZE and bytes(data[end - _ID3V1_SIZE : end - 125]) == b"TAG":
        end -= _ID3V1_SIZE
    if end - start >= _APE_FOOTER and bytes(data[end - 32 : end - 24]) == b"APETAGEX":
        size = int.from_bytes(data[end - 20 : end - 16], "little")
        flags = int.from_bytes(data[end - 12 : end - 8], "little")
        total = size + (_APE_FOOTER if flags & _APE_HAS_HEADER else 0)
        if _APE_FOOTER <= total <= end - start:
            end -= total
    return end


def _confirmed(data: Buffer, pos: int, end: int) -> FrameHeader | None:
    """A header at `pos` that the next frame's header agrees with (or that runs to the end)."""
    head = parse_header(data, pos)
    if head is None:
        return None
    nxt = pos + head.length
    if nxt + 4 > end:
        return head
    following = parse_header(data, nxt)
    if following is None or following.sample_rate != head.sample_rate:
        return None
    return head


def _resync(data: Buffer, pos: int, end: int) -> tuple[int, FrameHeader] | None:
    while True:
        pos = data.find(b"\xff", pos, end)
        if pos < 0:
            return None
        head = _confirmed(data, pos, end)
        if head is not None:
            return pos, head
        pos += 1


def first_frame(data: Buffer) -> FrameHeader | None:
    """The first real frame in the opening bytes of a file (after an ID3v2 tag that fits in
    them), or None. Used by the open's head check and its bitrate-based duration estimate."""
    start = id3v2_size(data)
    if start >= len(data):
        return None
    found = _resync(data, start, len(data))
    return found[1] if found else None


def walk(data: Buffer) -> Walk:
    """Walk every frame. Raises MediaRefused("unsupported_audio") when the bytes aren't an MP3
    we can read: under 30 s of frames, or frames under 90% of the bytes between the tags."""
    start = id3v2_size(data)
    end = _audio_end(data, start)
    offsets, starts = array("Q"), array("d")
    frame_bytes = 0
    # Time is base + samples / rate, reset when the rate changes, so frame starts are exact.
    base_s, run_samples, run_rate = 0.0, 0, 0
    pos, stop, head = start, start, None
    while pos + 4 <= end:
        head = parse_header(data, pos) if head is not None else None
        if head is None:
            found = _resync(data, pos, end)
            if found is None:
                break
            pos, head = found
        if pos + head.length > end:
            break  # a cut-off last frame
        if head.sample_rate != run_rate:
            if run_rate:
                base_s += run_samples / run_rate
            run_samples, run_rate = 0, head.sample_rate
        offsets.append(pos)
        starts.append(base_s + run_samples / run_rate)
        run_samples += head.samples
        frame_bytes += head.length
        pos += head.length
        stop = pos
    duration_s = base_s + (run_samples / run_rate if run_rate else 0.0)
    if duration_s < MIN_FRAMES_S or frame_bytes < MIN_FRAME_SHARE * (end - start):
        raise MediaRefused("unsupported_audio")
    return Walk(data, offsets, starts, stop, duration_s)


def split(
    walked: Walk, windows: Sequence[Window], *, max_piece_bytes: int = MAX_PIECE_BYTES
) -> list[Piece]:
    """One piece per window, cut at the first frame at or after the window's start (5R3).

    `windows` must be `plan_windows(floor(walked.duration_s))`: one source for both, so the
    counts always match. A piece over `max_piece_bytes` (above ~190 kbps) can't be sent inline:
    MediaRefused("unsupported_audio").
    """
    if not windows or windows[-1].end_s != math.floor(walked.duration_s):
        raise ValueError("windows weren't planned from this walk's duration")
    cuts = [bisect_left(walked.starts, w.start_s) for w in windows]
    increasing = all(a < b for a, b in zip(cuts, cuts[1:], strict=False))
    if cuts[0] != 0 or cuts[-1] >= walked.frames or not increasing:
        raise ValueError(f"windows don't map to distinct frames: {cuts}")
    bounds = [walked.offsets[i] for i in cuts] + [walked.stop]
    view = memoryview(walked.data)
    pieces = []
    for window, cut, a, b in zip(windows, cuts, bounds, bounds[1:], strict=False):
        if b - a > max_piece_bytes:
            raise MediaRefused("unsupported_audio")
        pieces.append(Piece(window.index, walked.starts[cut], view[a:b]))
    if len(pieces) != len(windows):
        raise ValueError(f"{len(pieces)} pieces for {len(windows)} windows")
    return pieces
