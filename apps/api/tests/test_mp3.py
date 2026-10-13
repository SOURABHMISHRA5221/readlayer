"""MP3 frame walk and time-only pieces (Media plan §C, Round 5 5.4, 5R1, 5R3, 5R4).

Streams are synthetic: valid Layer III headers followed by zero bytes. Sample rates are picked
so frames have exact lengths: MPEG 1 at 48 kHz and MPEG 2 at 24 kHz are 24 ms a frame, MPEG 2.5
at 12 kHz is 48 ms.
"""

import math

import pytest

from app.media import mp3
from app.media.refusals import MediaRefused
from app.media.transcript import plan_windows

# (version bits, sample-rate index) → MPEG 1 at 48 kHz, MPEG 2 at 24 kHz, MPEG 2.5 at 12 kHz.
MPEG1, MPEG2, MPEG25 = 0b11, 0b10, 0b00
_BITRATE_INDEX = {
    MPEG1: {32: 1, 64: 5, 128: 9, 192: 11, 320: 14},
    MPEG2: {8: 1, 32: 4, 64: 8, 160: 14},
    MPEG25: {8: 1, 32: 4},
}
_SR_INDEX_48K_FAMILY = 1  # 48000 / 24000 / 12000


def frame(kbps: int = 32, version: int = MPEG1, padding: int = 0) -> bytes:
    """One Layer III frame: header + zero payload, the right length for its bitrate."""
    b1 = 0xE0 | (version << 3) | (0b01 << 1) | 1  # sync, version, Layer III, no CRC
    b2 = (_BITRATE_INDEX[version][kbps] << 4) | (_SR_INDEX_48K_FAMILY << 2) | (padding << 1)
    header = bytes([0xFF, b1, b2, 0xC4])  # mono, emphasis none
    rate = {MPEG1: 48000, MPEG2: 24000, MPEG25: 12000}[version]
    coeff = 144 if version == MPEG1 else 72
    length = coeff * kbps * 1000 // rate + padding
    return header + bytes(length - 4)


def stream(seconds: float, kbps: int = 32, version: int = MPEG1) -> bytes:
    """CBR frames covering `seconds` (rounded to whole 24 ms frames)."""
    n = round(seconds / 0.024)
    return frame(kbps, version) * n


def id3v2(size: int) -> bytes:
    """An ID3v2.4 tag whose body is `size` bytes (syncsafe length)."""
    syncsafe = bytes([(size >> s) & 0x7F for s in (21, 14, 7, 0)])
    return b"ID3\x04\x00\x00" + syncsafe + bytes(size)


def id3v1() -> bytes:
    return b"TAG" + bytes(125)


def ape(size: int = 64, header: bool = True) -> bytes:
    """An APEv2 tag: optional 32-byte header, `size - 32` item bytes, 32-byte footer."""
    flags = (1 << 31) if header else 0
    block = (
        b"APETAGEX"
        + (2000).to_bytes(4, "little")
        + size.to_bytes(4, "little")
        + (0).to_bytes(4, "little")
        + flags.to_bytes(4, "little")
        + bytes(8)
    )
    return (block if header else b"") + bytes(size - 32) + block


# --- frame headers ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("version", "kbps", "length", "seconds"),
    [
        (MPEG1, 32, 96, 0.024),
        (MPEG1, 128, 384, 0.024),
        (MPEG1, 320, 960, 0.024),
        (MPEG2, 32, 96, 0.024),
        (MPEG2, 160, 480, 0.024),
        (MPEG25, 8, 48, 0.048),
    ],
)
def test_header_lengths_and_durations(version, kbps, length, seconds):
    head = mp3.parse_header(frame(kbps, version))
    assert head is not None
    assert head.length == length
    assert head.bitrate_kbps == kbps
    assert head.seconds == pytest.approx(seconds)


def test_padding_adds_a_byte():
    head = mp3.parse_header(frame(128, padding=1))
    assert head is not None and head.length == 385


@pytest.mark.parametrize(
    "header",
    [
        b"\xff\xfb\x00\xc4",  # free-format bitrate
        b"\xff\xfb\xf0\xc4",  # bitrate index 15
        b"\xff\xfb\x9c\xc4",  # sample-rate index 3
        b"\xff\xeb\x90\xc4",  # version bits 01 (reserved)
        b"\xff\xfd\x90\xc4",  # Layer II
        b"\xff\xfb\x90\xc6",  # emphasis 10 (reserved)
        b"\xfe\xfb\x90\xc4",  # no sync
        b"\xff\xfb\x90",  # short
    ],
)
def test_invalid_headers(header):
    assert mp3.parse_header(header) is None


# --- tags ------------------------------------------------------------------------------------


def test_id3v2_size():
    assert mp3.id3v2_size(id3v2(1000)[:10]) == 1010
    assert mp3.id3v2_size(b"\xff\xfb\x90\xc4" + bytes(6)) == 0
    assert mp3.id3v2_size(b"ID3") == 0  # too short to tell


def test_id3v2_size_with_footer_flag():
    tag = bytearray(id3v2(100))
    tag[5] = 0x10
    assert mp3.id3v2_size(bytes(tag[:10])) == 120


# --- first_frame (the open's head check) -----------------------------------------------------


def test_first_frame_after_tag_and_junk():
    data = id3v2(500) + b"\x00\xff\x12junk" + frame(128) * 3
    head = mp3.first_frame(data)
    assert head is not None and head.bitrate_kbps == 128


def test_first_frame_of_a_buffer_that_starts_mid_stream():
    data = bytes(37) + frame(64) * 2
    head = mp3.first_frame(data)
    assert head is not None and head.bitrate_kbps == 64


def test_first_frame_accepts_a_frame_cut_off_by_the_buffer_end():
    assert mp3.first_frame(frame(128) + frame(128)[:50]) is not None


def test_first_frame_needs_the_next_header_to_agree():
    # A lone sync pattern followed by junk is a false sync, not a frame.
    data = frame(128)[:4] + b"\x01" * 600
    assert mp3.first_frame(data) is None


def test_first_frame_rejects_non_mp3():
    assert mp3.first_frame(b"<html><body>not audio</body></html>" * 100) is None
    assert mp3.first_frame(b"") is None


def test_first_frame_with_tag_past_the_buffer_returns_none():
    # 5R1: the caller reads id3v2_size and fetches the bytes at the tag's end instead.
    assert mp3.first_frame(id3v2(1_000_000)[:65536]) is None


# --- walk ------------------------------------------------------------------------------------


def test_walk_cbr_duration_and_fingerprint():
    data = stream(60)
    walked = mp3.walk(data)
    assert walked.frames == 2500
    assert walked.duration_s == pytest.approx(60.0)
    assert walked.fingerprint == f"2500:{len(data)}"


def test_walk_vbr():
    data = (frame(32) + frame(128) + frame(320)) * 1000
    walked = mp3.walk(data)
    assert walked.frames == 3000
    assert walked.duration_s == pytest.approx(72.0)


def test_walk_mpeg2():
    walked = mp3.walk(stream(45, kbps=32, version=MPEG2))
    assert walked.duration_s == pytest.approx(45.0)


def test_walk_skips_tags_at_both_ends():
    data = id3v2(1_000_000) + stream(42) + ape(200) + id3v1()
    walked = mp3.walk(data)
    assert walked.duration_s == pytest.approx(42.0)
    assert walked.fingerprint == f"{walked.frames}:{len(data)}"


def test_walk_skips_footer_only_ape_tag():
    walked = mp3.walk(stream(42) + ape(96, header=False))
    assert walked.duration_s == pytest.approx(42.0)


def test_walk_resyncs_on_junk_between_frames():
    junk = b"\x00\xff\xfe\x13" * 25  # includes a false 0xFF
    data = stream(21) + junk + stream(21)
    walked = mp3.walk(data)
    assert walked.duration_s == pytest.approx(42.0)


def test_walk_drops_a_truncated_last_frame():
    data = stream(42) + frame(128)[:100]
    assert mp3.walk(data).duration_s == pytest.approx(42.0)


def test_walk_refuses_under_thirty_seconds_of_frames():
    with pytest.raises(MediaRefused) as exc:
        mp3.walk(stream(29.9))
    assert exc.value.code == "unsupported_audio"


def test_walk_refuses_when_frames_are_under_ninety_percent_of_audio_bytes():
    data = stream(40)
    junk = b"\x00" * (len(data) // 8)  # frames ≈ 88.9% of the bytes
    with pytest.raises(MediaRefused) as exc:
        mp3.walk(data + junk)
    assert exc.value.code == "unsupported_audio"


def test_walk_ninety_percent_ignores_tag_bytes():
    # 5R1: a big cover-art tag isn't "bytes outside frames".
    walked = mp3.walk(id3v2(5_000_000) + stream(42))
    assert walked.duration_s == pytest.approx(42.0)


def test_walk_refuses_non_mp3():
    with pytest.raises(MediaRefused):
        mp3.walk(b"ftypM4A " + bytes(2_000_000))


# --- split -----------------------------------------------------------------------------------


def _split(data: bytes, **kwargs) -> tuple[mp3.Walk, list, list[mp3.Piece]]:
    walked = mp3.walk(data)
    windows = plan_windows(math.floor(walked.duration_s))
    return walked, windows, mp3.split(walked, windows, **kwargs)


@pytest.mark.parametrize(
    ("seconds", "count"),
    [(659.4, 1), (659.6, 1), (660.0, 2), (660.4, 2), (1320.0, 3), (1259.0, 2), (40.0, 1)],
)
def test_pieces_match_windows_at_fractional_tails(seconds, count):
    # 5R3: piece i is window i, whatever the tail; 48 kHz frames make durations exact.
    frames = math.floor(seconds / 0.024 + 0.5)
    walked, windows, pieces = _split(frame(32) * frames)
    assert len(windows) == count
    assert len(pieces) == len(windows)
    for piece, window in zip(pieces, windows, strict=True):
        assert piece.index == window.index
        assert window.start_s <= piece.start_s < window.start_s + 0.024 + 1e-9


def test_pieces_cut_on_frame_boundaries_and_cover_every_frame():
    data = id3v2(300) + stream(1300, kbps=64) + id3v1()
    walked, windows, pieces = _split(data)
    assert len(pieces) == 3
    joined = b"".join(bytes(p.data) for p in pieces)
    assert joined == stream(1300, kbps=64)  # tags left out, frames in order, nothing lost
    for piece in pieces:
        assert mp3.parse_header(piece.data) is not None
        assert len(piece.data) % len(frame(64)) == 0


def test_piece_times_follow_the_walk_not_the_byte_rate():
    data = (frame(32) * 10000) + (frame(192) * 20000)  # 240 s cheap + 480 s dear
    _, windows, pieces = _split(data)
    assert [w.start_s for w in windows] == [0, 600]
    assert pieces[1].start_s == pytest.approx(600.0)
    assert len(pieces[1].data) == 5000 * len(frame(192))


def test_pieces_are_views_not_copies():
    data = bytearray(stream(700))
    walked, _, pieces = _split(data)
    assert all(isinstance(p.data, memoryview) for p in pieces)
    assert pieces[0].data.obj is data


def test_piece_over_the_byte_cap_is_refused():
    with pytest.raises(MediaRefused) as exc:
        _split(stream(700, kbps=128), max_piece_bytes=9_000_000)
    assert exc.value.code == "unsupported_audio"
    assert mp3.MAX_PIECE_BYTES == 14_500_000


def test_split_asserts_windows_belong_to_this_walk():
    walked = mp3.walk(stream(100))
    with pytest.raises(ValueError):
        mp3.split(walked, plan_windows(1300))
