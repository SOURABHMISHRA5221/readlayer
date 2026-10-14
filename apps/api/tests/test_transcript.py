from collections import Counter

import pytest

from app.ingest.extract import MAX_PARAGRAPHS
from app.llm import InvalidTranscript
from app.media.transcript import (
    TimedParagraph,
    TranscriptParagraph,
    TranscriptRefused,
    TranscriptWindow,
    Window,
    WindowText,
    assemble,
    check_window,
    is_english,
    main_language,
    parse_clock,
    plan_for,
    plan_windows,
)


def words(n: int, word: str = "word", end: str = ".") -> str:
    return " ".join([word] * n) + end


def out(*paragraphs: tuple[str, str], language: str = "en") -> TranscriptWindow:
    return TranscriptWindow(
        language=language,
        paragraphs=[TranscriptParagraph(start=s, text=t) for s, t in paragraphs],
    )


def wt(*paragraphs: tuple[int, str], language: str = "en") -> WindowText:
    return WindowText(language, tuple(TimedParagraph(s, t) for s, t in paragraphs))


# ---------------------------------------------------------------- windows and clocks


def test_plan_windows_covers_the_recording_back_to_back():
    assert plan_windows(949) == [Window(0, 0, 600), Window(1, 600, 949)]
    assert plan_windows(600) == [Window(0, 0, 600)]
    assert plan_windows(30) == [Window(0, 0, 30)]
    assert plan_windows(0) == []


def test_a_tail_under_a_minute_joins_the_window_before():
    assert plan_windows(1230) == [Window(0, 0, 600), Window(1, 600, 1230)]
    assert plan_windows(1260) == [Window(0, 0, 600), Window(1, 600, 1200), Window(2, 1200, 1260)]


def test_a_video_is_one_window_and_audio_keeps_ten_minute_pieces():
    assert plan_for("youtube", 949) == [Window(0, 0, 949)]
    assert plan_for("youtube", 1190) == [Window(0, 0, 1190)]
    assert plan_for("youtube", 0) == []
    assert plan_for("audio", 1230) == plan_windows(1230)


@pytest.mark.parametrize(
    ("text", "seconds"), [("00:02", 2), ("15:26", 926), ("0:00", 0), ("1:02:03", 3723)]
)
def test_parse_clock(text, seconds):
    assert parse_clock(text) == seconds


@pytest.mark.parametrize("text", ["1549", "15:6", "abc", "1:2:3:4", ""])
def test_parse_clock_refuses_non_clock_text(text):
    with pytest.raises(ValueError):
        parse_clock(text)


# ---------------------------------------------------------------- one window


def test_absolute_times_are_kept():
    got = check_window(
        out(("10:05", "a b c."), ("12:00", "d e.")), Window(1, 600, 1200), relative_only=False
    )
    assert [p.start_s for p in got.paragraphs] == [605, 720]


def test_relative_times_are_shifted_to_the_recording_clock():
    got = check_window(
        out(("00:05", "a b c."), ("02:00", "d e.")), Window(1, 600, 1200), relative_only=False
    )
    assert [p.start_s for p in got.paragraphs] == [605, 720]


def test_audio_pieces_are_always_relative():
    # 09:58 would also fit as absolute in a window starting at 0, but not this one
    got = check_window(
        out(("00:00", "a."), ("09:58", "b.")), Window(1, 600, 1200), relative_only=True
    )
    assert [p.start_s for p in got.paragraphs] == [600, 1198]


def test_a_time_outside_the_window_is_invalid():
    with pytest.raises(InvalidTranscript):
        check_window(
            out(("05:00", "a."), ("25:00", "b.")), Window(1, 600, 1200), relative_only=False
        )


def test_a_looping_paragraph_is_invalid():
    looped = "and the same long sentence again and again"
    with pytest.raises(InvalidTranscript):
        check_window(
            out(*[(f"0{i}:00", looped) for i in range(3)]), Window(0, 0, 600), relative_only=False
        )


def test_short_repeats_are_fine():
    got = check_window(
        out(*[(f"0{i}:00", "Thank you.") for i in range(3)]), Window(0, 0, 600), relative_only=False
    )
    assert len(got.paragraphs) == 3


def test_more_than_300_words_a_minute_is_invalid():
    with pytest.raises(InvalidTranscript):
        check_window(out(("00:00", words(301))), Window(0, 0, 60), relative_only=False)


def test_times_are_made_non_decreasing_and_kept_inside_the_window():
    got = check_window(
        out(("02:00", "a."), ("01:00", "b."), ("10:03", "c.")),
        Window(0, 0, 600),
        relative_only=False,
    )
    assert [p.start_s for p in got.paragraphs] == [120, 120, 600]


def test_a_silent_window_is_fine():
    assert check_window(out(), Window(0, 0, 600), relative_only=False).paragraphs == ()


def test_whitespace_is_collapsed_and_empty_paragraphs_dropped():
    got = check_window(
        out(("00:00", "  a \n b  "), ("00:05", "  ")), Window(0, 0, 600), relative_only=False
    )
    assert got.paragraphs == (TimedParagraph(0, "a b"),)


# ---------------------------------------------------------------- language


def test_main_language_is_the_majority_by_words():
    windows = [wt((0, words(30)), language="hi"), wt((600, words(50)), language="en-US")]
    assert main_language(windows) == "en-us"
    assert is_english("en-US") and is_english("en") and not is_english("hi")


def test_a_non_english_recording_is_refused():
    with pytest.raises(TranscriptRefused) as err:
        assemble([wt((0, words(100)), language="hi")])
    assert err.value.code == "not_english"


def test_under_80_words_is_no_speech():
    with pytest.raises(TranscriptRefused) as err:
        assemble([wt((0, words(79))), wt()])
    assert err.value.code == "no_speech"


# ---------------------------------------------------------------- assembly


def test_a_sentence_cut_by_the_window_boundary_is_joined():
    # The measured case: "... difficult to see that AIG was offering" | "insurance to ..."
    first = wt((3000, words(40)), (3543, words(30, end=" that AIG was offering")))
    second = wt((3600, "insurance to depository institutions " + words(30)))
    got = assemble([first, second])
    assert [p.start_s for p in got] == [3000, 3543]
    assert "AIG was offering insurance to depository" in got[1].text


def test_no_join_after_closing_punctuation_or_before_a_capital():
    first = wt((0, words(40)), (300, words(40)))
    second = wt((600, "Next " + words(40)))
    assert len(assemble([first, second])) == 3
    first = wt((0, words(40)), (300, words(40, end="")))
    assert len(assemble([first, second])) == 3


def test_short_paragraphs_merge_into_the_next_in_the_same_window():
    got = assemble([wt((0, "Hello."), (5, "Welcome back."), (10, words(80)))])
    assert got == [TimedParagraph(0, "Hello. Welcome back. " + words(80))]


def test_a_short_last_paragraph_merges_into_the_one_before():
    got = assemble([wt((0, words(40)), (300, words(40)), (590, "Thank you."))])
    assert len(got) == 2 and got[-1].text.endswith("Thank you.")
    assert got[-1].start_s == 300


def test_above_the_paragraph_cap_neighbours_merge_until_it_fits():
    windows = [wt(*[(i, words(25)) for i in range(250)])]
    got = assemble(windows)
    assert len(got) == MAX_PARAGRAPHS
    assert [p.start_s for p in got] == sorted(p.start_s for p in got)


def test_too_long_is_refused_never_cut():
    windows = [wt(*[(i, words(150, word="longword")) for i in range(200)])]  # ~180k chars
    with pytest.raises(TranscriptRefused) as err:
        assemble(windows)
    assert err.value.code == "too_long"


def test_words_are_never_changed_only_grouped():
    raw = [
        wt(
            (0, "So, um, here's the thing."),
            (4, words(30, word="alpha")),
            (60, words(10, word="beta", end="")),
        ),
        wt((600, "gamma continues " + words(40, word="gamma")), (900, "Bye.")),
    ]
    got = assemble(raw)
    before = Counter(w for window in raw for p in window.paragraphs for w in p.text.split())
    after = Counter(w for p in got for w in p.text.split())
    assert before == after
    assert [p.start_s for p in got] == sorted(p.start_s for p in got)
