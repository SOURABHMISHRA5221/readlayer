import json

import httpx
import pytest
from pydantic import SecretStr

from app.config import Settings
from app.media.refusals import MediaRefused, MediaUnavailable
from app.media.sources import youtube_info

VID = "d6fUwCBvVc0"


def settings(**overrides) -> Settings:
    return Settings(_env_file=None, youtube_api_key=SecretStr("k3y"), **overrides)


def video(**changes) -> dict:
    item = {
        "id": VID,
        "status": {"privacyStatus": "public", "uploadStatus": "processed", "embeddable": True},
        "snippet": {
            "title": "Monetary policy explained",
            "channelTitle": "Econ Lectures",
            "publishedAt": "2026-09-01T10:00:00Z",
            "liveBroadcastContent": "none",
            "defaultAudioLanguage": "en-GB",
            "thumbnails": {"high": {"url": "https://i.ytimg.com/vi/x/hqdefault.jpg"}},
        },
        "contentDetails": {"duration": "PT15M49S"},
    }
    for path, value in changes.items():
        section, key = path.split("__")
        item[section][key] = value
    return item


def transport(items: list[dict] | None = None, status: int = 200, seen: list | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, content=json.dumps({"items": items or []}))

    return httpx.MockTransport(handler)


async def test_a_public_embeddable_english_video_passes():
    seen: list[httpx.Request] = []
    info = await youtube_info(VID, settings(), transport([video()], seen=seen))
    assert info.title == "Monetary policy explained"
    assert info.site == "Econ Lectures"
    assert info.duration_s == 949
    assert info.language == "en-GB"
    assert info.image == "https://i.ytimg.com/vi/x/hqdefault.jpg"
    (request,) = seen
    assert request.url.params["part"] == "contentDetails,status,snippet"
    assert request.url.params["id"] == VID  # only the public id and our key leave the server


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"status__privacyStatus": "unlisted"}, "not_public"),
        ({"status__uploadStatus": "uploaded"}, "not_public"),
        ({"status__embeddable": False}, "not_embeddable"),
        ({"contentDetails__contentRating": {"ytRating": "ytAgeRestricted"}}, "not_embeddable"),
        ({"snippet__liveBroadcastContent": "upcoming"}, "live"),
        ({"contentDetails__duration": "P0D"}, "live"),
        ({"contentDetails__duration": "PT25S"}, "no_speech"),
        ({"contentDetails__duration": "PT1H8M"}, "too_long"),
        ({"snippet__defaultAudioLanguage": "hi"}, "not_english"),
        ({"snippet__title": "मौद्रिक नीति समझाई गई"}, "not_english"),
    ],
)
async def test_refusals_one_by_one(changes, code):
    with pytest.raises(MediaRefused) as err:
        await youtube_info(VID, settings(), transport([video(**changes)]))
    assert err.value.code == code


async def test_no_declared_language_is_allowed_and_left_unknown():
    item = video()
    del item["snippet"]["defaultAudioLanguage"]
    info = await youtube_info(VID, settings(), transport([item]))
    assert info.language is None


async def test_the_cap_is_a_setting():
    info = await youtube_info(VID, settings(media_max_video_s=4000), transport(
        [video(contentDetails__duration="PT1H5M")]
    ))  # fmt: skip
    assert info.duration_s == 3900


async def test_the_default_cap_is_twenty_minutes():
    """One whole-URL call per video, so the cap is 20 minutes (plan Round 4, R4.2)."""
    info = await youtube_info(VID, settings(), transport([video(contentDetails__duration="PT20M")]))
    assert info.duration_s == 1200
    with pytest.raises(MediaRefused) as err:
        await youtube_info(VID, settings(), transport([video(contentDetails__duration="PT20M1S")]))
    assert err.value.code == "too_long"


async def test_not_found_is_not_public():
    with pytest.raises(MediaRefused) as err:
        await youtube_info(VID, settings(), transport([]))
    assert err.value.code == "not_public"


async def test_an_api_error_is_unavailable_and_logs_no_url(caplog):
    with pytest.raises(MediaUnavailable):
        await youtube_info(VID, settings(), transport(status=403))
    assert "k3y" not in caplog.text and "googleapis" not in caplog.text


async def test_no_key_means_media_off():
    with pytest.raises(MediaRefused) as err:
        await youtube_info(VID, Settings(_env_file=None), transport([video()]))
    assert err.value.code == "media_off"
