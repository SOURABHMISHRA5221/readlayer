import json
from pathlib import Path

import pytest

from app.ingest.urls import url_hash
from app.media.urls import ApplePodcast, AudioFile, YouTube, classify, content_id, kind

# Shared with the extension's Open in Gloss (apps/extension/test/youtube.test.ts, decision 62).
YOUTUBE = json.loads((Path(__file__).parent / "fixtures" / "youtube_urls.json").read_text())
VID = YOUTUBE["video_id"]


@pytest.mark.parametrize("url", YOUTUBE["videos"])
def test_every_youtube_form_maps_to_one_video(url):
    media = classify(url)
    assert media == YouTube(VID)
    assert media.canonical == YOUTUBE["canonical"]
    assert content_id(media) == url_hash(YOUTUBE["canonical"])
    assert kind(media) == "video"


@pytest.mark.parametrize("url", YOUTUBE["not_videos"])
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
