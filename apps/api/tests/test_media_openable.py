import pytest

from app.config import Settings
from app.ingest.models import ContentDoc, Media, is_corpus
from app.media import openable
from app.media.openable import open_here
from app.store.media_repo import media_day_path
from app.store.spend_repo import today_utc

VIDEO = "https://www.youtube.com/watch?v=d6fUwCBvVc0"


def settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


@pytest.fixture(autouse=True)
def fresh_cache():
    openable.reset()
    yield
    openable.reset()


@pytest.mark.parametrize(
    ("url", "fmt", "duration", "expected"),
    [
        ("https://news.example/a", "article", None, True),
        (VIDEO, "video", 949, True),
        (VIDEO, "video", 1800, True),
        (VIDEO, "video", 1801, False),  # past MEDIA_MAX_VIDEO_S
        (VIDEO, "video", None, False),  # unknown length
        ("https://vimeo.com/123", "video", 600, False),
        ("https://open.spotify.com/episode/x", "podcast", 1200, False),
        ("https://podcasts.apple.com/us/podcast/x/id1?i=2", "podcast", 1200, False),  # step 6
    ],
)
async def test_open_here_for_signed_in_readers(url, fmt, duration, expected):
    assert await open_here(url, fmt, duration, settings(), anonymous=False) is expected


async def test_media_off_leaves_only_articles():
    s = settings(media_enabled=False)
    assert await open_here(VIDEO, "video", 600, s, anonymous=False) is False
    assert await open_here("https://news.example/a", "article", None, s, anonymous=False)


async def test_demo_readers_lose_open_here_once_the_shared_cap_is_used(docs):
    s = settings(anon_global_media_daily_cap=2)
    docs.docs[media_day_path(today_utc())] = {"anonymous": 2}
    assert await open_here(VIDEO, "video", 600, s, anonymous=True) is False
    assert await open_here(VIDEO, "video", 600, s, anonymous=False) is True
    assert await open_here("https://news.example/a", "article", None, s, anonymous=True)


async def test_the_shared_count_is_read_once_a_minute(docs):
    s = settings(anon_global_media_daily_cap=2)
    assert await open_here(VIDEO, "video", 600, s, anonymous=True) is True
    docs.docs[media_day_path(today_utc())] = {"anonymous": 2}
    assert await open_here(VIDEO, "video", 600, s, anonymous=True) is True  # cached
    openable.reset()
    assert await open_here(VIDEO, "video", 600, s, anonymous=True) is False


def test_a_recording_is_never_corpus():
    # Plan 2.4: onboarding discover, the pre-read index, the landing demo and the highlight
    # measurements read corpus docs only, so they never see a transcript.
    doc = ContentDoc(
        content_id="c", url=VIDEO, final_url=VIDEO, title="t", site="s",
        source="user_ingested", fetched_at="2026-10-14", paragraphs=[], demands=[],
        demands_dropped=0, llm_calls=[], media=Media(kind="youtube", video_id="d6fUwCBvVc0",
                                                     duration_s=949),
    )  # fmt: skip
    assert not is_corpus(doc)
