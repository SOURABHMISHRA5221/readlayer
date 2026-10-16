"""Why a recording can't be read in Gloss, in the reader's words (Media plan §F)."""

OPEN_ORIGINAL = "Use “Open original” to watch or listen on the publisher's site."

MESSAGES: dict[str, str] = {
    "media_off": "Videos and podcasts can't be opened in Gloss right now.",
    "apple_link_only": "Gloss opens podcast episodes from their Apple Podcasts link.",
    "not_public": "This video isn't public, so Gloss can't read it.",
    "not_embeddable": "This video can't be played outside YouTube.",
    "live": "Live streams can't be opened in Gloss.",
    "too_long": "Too long for Gloss for now: videos up to 10 minutes, podcasts up to 12.",
    "not_english": "Gloss reads English recordings only for now.",
    "no_speech": "Gloss couldn't find enough speech in this recording.",
    "episode_not_found": "Gloss couldn't find this episode's audio.",
    "not_an_episode": "This is a show page. Open a single episode instead.",
    "unsupported_audio": "This episode's audio format can't be read by Gloss.",
    "too_costly": "This recording took too long to transcribe, so Gloss stopped.",
    "media_unavailable": "Gloss couldn't look this recording up just now.",
}
REFUSAL_CODES = frozenset(MESSAGES)
# Answers about this build or its switches, not the recording: never remembered, so turning a
# switch back on works at once (5R7).
NOT_REMEMBERED = frozenset({"media_off", "apple_link_only"})


def message(code: str) -> str:
    return f"{MESSAGES.get(code, MESSAGES['media_unavailable'])} {OPEN_ORIGINAL}"


class MediaRefused(Exception):
    """The recording is refused for a known reason; `code` is one of REFUSAL_CODES. Remembered
    for the UTC day so the same URL is never looked up or paid for again (plan 2.2)."""

    def __init__(self, code: str) -> None:
        if code not in REFUSAL_CODES:
            raise ValueError(f"unknown media refusal: {code}")
        super().__init__(code)
        self.code = code


class MediaCapReached(Exception):
    """A daily media cap: per reader, all demo readers, lookups, or the media budget (429)."""


class MediaUnavailable(Exception):
    """A lookup failed for a transient reason (not remembered; the reader may retry)."""
