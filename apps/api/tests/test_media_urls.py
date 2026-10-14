import pytest

from app.ingest.urls import url_hash
from app.media.urls import ApplePodcast, AudioFile, YouTube, classify, content_id, kind

VID = "d6fUwCBvVc0"


@pytest.mark.parametrize(
    "url",
    [
        f"https://www.youtube.com/watch?v={VID}",
        f"https://youtube.com/watch?v={VID}&t=42s",
        f"https://m.youtube.com/watch?feature=share&v={VID}",
        f"http://www.youtube.com/watch?v={VID}",
        f"https://youtu.be/{VID}",
        f"https://youtu.be/{VID}?si=abc",
        f"https://www.youtube.com/shorts/{VID}",
        f"https://www.youtube.com/embed/{VID}",
        f"  https://WWW.YouTube.com/watch?v={VID}  ",
    ],
)
def test_every_youtube_form_maps_to_one_video(url):
    media = classify(url)
    assert media == YouTube(VID)
    assert media.canonical == f"https://www.youtube.com/watch?v={VID}"
    assert content_id(media) == url_hash(f"https://www.youtube.com/watch?v={VID}")
    assert kind(media) == "video"


@pytest.mark.parametrize(
    "url",
    [
        "https://music.youtube.com/watch?v=d6fUwCBvVc0",  # not in scope
        "https://www.youtube.com/watch?v=short",  # not 11 characters
        "https://www.youtube.com/watch?v=d6fUwCBvVc0&v=xFPILM4UUSg",  # two ids
        "https://www.youtube.com/@channel",
        "https://www.youtube.com/playlist?list=PL123",
        "https://youtu.be/",
        "https://youtube.com.evil.example/watch?v=d6fUwCBvVc0",  # look-alike hosts
        "https://evilyoutube.com/watch?v=d6fUwCBvVc0",
        "https://youtu.be.evil.example/d6fUwCBvVc0",
        "https://user:pw@www.youtube.com/watch?v=d6fUwCBvVc0",
        "ftp://www.youtube.com/watch?v=d6fUwCBvVc0",
        "javascript:alert(1)//www.youtube.com/watch?v=d6fUwCBvVc0",
        "https://www.bbc.co.uk/news/articles/c1",
        "not a url",
    ],
)
def test_other_links_are_not_videos(url):
    assert not isinstance(classify(url), YouTube)


APPLE = (
    "https://podcasts.apple.com/ie/podcast/a-gas-tax-holiday-is-performative-nonsense/"
    "id1523898793?i=1000770325688"
)


def test_apple_episode_link():
    media = classify(APPLE)
    assert media == ApplePodcast("1523898793", "1000770325688")
    assert media.canonical == "https://podcasts.apple.com/podcast/id1523898793?i=1000770325688"
    assert kind(media) == "podcast"


def test_apple_spellings_share_one_id():
    other = "https://podcasts.apple.com/us/podcast/other-slug/id1523898793?i=1000770325688&l=en-GB"
    assert content_id(classify(APPLE)) == content_id(classify(other))


def test_apple_show_page_has_no_episode():
    media = classify("https://podcasts.apple.com/us/podcast/the-show/id1523898793")
    assert media == ApplePodcast("1523898793", None)


@pytest.mark.parametrize(
    "url",
    [
        "https://podcasts.apple.com/us/podcast/x/id15?i=abc",
        "https://podcasts.apple.com/us/podcast/x/id15?i=1&i=2",
        "https://podcasts.apple.com/us/browse",
        "https://podcasts.apple.com.evil.example/us/podcast/x/id15?i=1",
    ],
)
def test_malformed_apple_links_are_not_episodes(url):
    assert not isinstance(classify(url), ApplePodcast)


def test_an_https_mp3_is_an_audio_file():
    media = classify("https://media.transistor.fm/d14092c5/4fe98c87.mp3?utm_source=x")
    assert media == AudioFile("https://media.transistor.fm/d14092c5/4fe98c87.mp3?utm_source=x")
    assert media.canonical == "https://media.transistor.fm/d14092c5/4fe98c87.mp3"


@pytest.mark.parametrize(
    "url",
    [
        "http://media.example.com/a.mp3",  # https only
        "https://media.example.com/a.m4a",
        "https://open.spotify.com/episode/abc",
    ],
)
def test_other_audio_is_not_ours(url):
    assert classify(url) is None
