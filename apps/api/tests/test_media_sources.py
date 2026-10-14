import json

import httpx
import pytest
from pydantic import SecretStr

from app.config import Settings
from app.ingest.safe_fetch import SafeFetcher
from app.media.refusals import MediaRefused, MediaUnavailable
from app.media.sources import apple_episode, estimated_duration_s, probe_audio, youtube_info
from tests.test_media_service import LONG_CAPS

VID = "d6fUwCBvVc0"


def settings(**overrides) -> Settings:
    return Settings(_env_file=None, youtube_api_key=SecretStr("k3y"), **(LONG_CAPS | overrides))


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


def test_the_default_caps_are_ten_minutes():
    """Media is minor support: one 10-minute window per recording (Sourabh, 2026-10-14)."""
    s = Settings(_env_file=None)
    assert (s.media_max_video_s, s.media_max_audio_s) == (600, 600)
    assert s.media_max_audio_bytes == 20_000_000


async def test_a_video_over_the_default_cap_is_too_long():
    s = Settings(_env_file=None, youtube_api_key=SecretStr("k3y"))
    info = await youtube_info(VID, s, transport([video(contentDetails__duration="PT10M")]))
    assert info.duration_s == 600
    with pytest.raises(MediaRefused) as err:
        await youtube_info(VID, s, transport([video(contentDetails__duration="PT10M1S")]))
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


# --- Apple Podcasts (plan Round 5 5.3, 5R11) -------------------------------------------------

SHOW, EP = "1200361736", "1000650934531"
EP_URL = "https://cdn.example/ep.mp3"


def episode(**changes) -> dict:
    item = {
        "wrapperType": "podcastEpisode",
        "kind": "podcast-episode",
        "trackId": int(EP),
        "trackName": "How central banks set rates",
        "collectionName": "The Indicator",
        "episodeUrl": EP_URL,
        "episodeFileExtension": "mp3",
        "trackTimeMillis": 1_320_000,
        "artworkUrl600": "https://is1-ssl.mzstatic.com/a/600x600bb.jpg",
        "releaseDate": "2026-09-30T08:00:00Z",
    }
    for key, value in changes.items():
        if value is None:
            item.pop(key, None)
        else:
            item[key] = value
    return item


def apple(results: list[dict] | None = None, status: int = 200, seen: list | None = None):
    show = {"wrapperType": "track", "kind": "podcast", "collectionId": int(SHOW)}

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        body = {"resultCount": 1 + len(results or []), "results": [show, *(results or [])]}
        return httpx.Response(status, content=json.dumps(body))

    return httpx.MockTransport(handler)


async def test_an_apple_episode_passes():
    seen: list[httpx.Request] = []
    other = episode(trackId=1, episodeUrl="https://cdn.example/other.mp3")
    info = await apple_episode(SHOW, EP, settings(), apple([other, episode()], seen=seen))
    assert info.title == "How central banks set rates"
    assert info.site == "The Indicator"
    assert info.duration_s == 1320
    assert info.audio_url == EP_URL
    assert info.image == "https://is1-ssl.mzstatic.com/a/600x600bb.jpg"
    assert info.published == "2026-09-30T08:00:00Z"
    assert info.language is None  # Apple never declares it: window 1 runs alone first (R8)
    (request,) = seen
    assert request.url.host == "itunes.apple.com"
    assert dict(request.url.params) == {"id": SHOW, "entity": "podcastEpisode", "limit": "200"}


async def test_a_show_page_is_refused_without_a_lookup():
    seen: list[httpx.Request] = []
    with pytest.raises(MediaRefused) as err:
        await apple_episode(SHOW, None, settings(), apple([episode()], seen=seen))
    assert err.value.code == "not_an_episode"
    assert seen == []


async def test_track_id_compared_as_a_number():
    info = await apple_episode(SHOW, EP, settings(), apple([episode(trackId=EP)]))
    assert info.audio_url == EP_URL


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"trackId": 42}, "episode_not_found"),
        ({"episodeUrl": None}, "episode_not_found"),
        ({"episodeUrl": "http://cdn.example/ep.mp3"}, "episode_not_found"),
        ({"episodeUrl": "https://cdn.example/" + "a" * 2050}, "episode_not_found"),
        ({"episodeFileExtension": "m4a"}, "unsupported_audio"),
        ({"trackTimeMillis": 2_701_000}, "too_long"),
        ({"trackTimeMillis": 20_000}, "no_speech"),
        ({"trackName": "केंद्रीय बैंक दरें कैसे तय करते हैं"}, "not_english"),
    ],
)
async def test_apple_refusals_one_by_one(changes, code):
    with pytest.raises(MediaRefused) as err:
        await apple_episode(SHOW, EP, settings(), apple([episode(**changes)]))
    assert err.value.code == code


async def test_missing_length_and_extension_fall_through_to_the_audio_checks():
    item = episode(trackTimeMillis=None, episodeFileExtension=None)
    info = await apple_episode(SHOW, EP, settings(), apple([item]))
    assert info.duration_s == 0  # unknown: estimated from the audio head, walked at transcribe


async def test_apple_fields_are_capped():
    item = episode(trackName="T" * 400, collectionName="S" * 200, artworkUrl600="http://x/a.jpg")
    info = await apple_episode(SHOW, EP, settings(), apple([item]))
    assert len(info.title) == 300 and len(info.site) == 120
    assert info.image is None


@pytest.mark.parametrize("status", [500, 403, 429])
async def test_an_apple_error_is_unavailable_and_logs_no_url(status, caplog):
    with pytest.raises(MediaUnavailable):
        await apple_episode(SHOW, EP, settings(), apple([episode()], status=status))
    assert "itunes" not in caplog.text and EP_URL not in caplog.text


async def test_an_apple_network_error_is_unavailable():
    def fail(request):
        raise httpx.ConnectError("down")

    with pytest.raises(MediaUnavailable):
        await apple_episode(SHOW, EP, settings(), httpx.MockTransport(fail))


async def test_apple_garbage_is_unavailable():
    bad = httpx.MockTransport(lambda r: httpx.Response(200, content=b"<html>"))
    with pytest.raises(MediaUnavailable):
        await apple_episode(SHOW, EP, settings(), bad)


# --- audio probe (5.3, 5R1, 5R5) -------------------------------------------------------------


def mp3_bytes(seconds: int = 60, tag: int = 0) -> bytes:
    """A 128 kbps MPEG 1 stream at 48 kHz (384-byte frames, 24 ms) behind an optional ID3v2."""
    header = b""
    if tag:
        header = b"ID3\x04\x00\x00" + bytes([(tag >> s) & 0x7F for s in (21, 14, 7, 0)])
        header += bytes(tag)
    frame = b"\xff\xfb\x94\xc4" + bytes(380)
    return header + frame * (seconds * 1000 // 24)


def audio_host(body: bytes, ctype: str = "audio/mpeg", honour_range: bool = True, seen=None):
    """A guarded fetcher whose CDN serves `body`, answering Range with 206 when asked to."""

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        wanted = request.headers.get("range")
        if wanted and honour_range:
            a, b = (int(x) for x in wanted.removeprefix("bytes=").split("-"))
            part = body[a : b + 1]
            rng = f"bytes {a}-{a + len(part) - 1}/{len(body)}"
            return httpx.Response(
                206, content=part, headers={"content-type": ctype, "content-range": rng}
            )
        return httpx.Response(200, content=body, headers={"content-type": ctype})

    async def resolve(host: str, port: int) -> list[str]:
        return ["93.184.215.34"]

    return SafeFetcher(resolver=resolve, transport=httpx.MockTransport(handler))


async def test_probe_reads_size_and_bitrate():
    body = mp3_bytes(60)
    probe = await probe_audio(EP_URL, settings(), audio_host(body))
    assert probe.total_bytes == len(body)
    assert probe.bitrate_kbps == 128
    assert probe.final_url == EP_URL
    assert estimated_duration_s(probe) == 60


async def test_probe_follows_a_tag_bigger_than_the_head():
    # 5R1: 1 MB of cover art; a second 16 KB ranged GET at the tag's end finds the frames.
    seen: list[httpx.Request] = []
    body = mp3_bytes(60, tag=1_000_000)
    probe = await probe_audio(EP_URL, settings(), audio_host(body, seen=seen))
    assert probe.bitrate_kbps == 128
    ranges = [r.headers.get("range") for r in seen if r.url.path != "/robots.txt"]
    assert ranges == ["bytes=0-65535", "bytes=1000010-1016393"]


async def test_probe_on_a_host_that_ignores_range():
    body = mp3_bytes(60, tag=100_000)
    probe = await probe_audio(EP_URL, settings(), audio_host(body, honour_range=False))
    assert probe.total_bytes == len(body) and probe.bitrate_kbps == 128


async def test_probe_refuses_a_file_over_the_byte_cap():
    with pytest.raises(MediaRefused) as err:
        await probe_audio(EP_URL, settings(media_max_audio_bytes=500_000), audio_host(mp3_bytes()))
    assert err.value.code == "too_long"


@pytest.mark.parametrize(
    ("body", "ctype"),
    [
        (b"<html>" + bytes(100_000), "audio/mpeg"),  # says MP3, isn't
        (mp3_bytes(), "audio/mp4"),
        (mp3_bytes(60, tag=10_000_000)[:200_000], "audio/mpeg"),  # tag runs past the file
    ],
)
async def test_probe_refuses_what_isnt_an_mp3(body, ctype):
    with pytest.raises(MediaRefused) as err:
        await probe_audio(EP_URL, settings(), audio_host(body, ctype=ctype))
    assert err.value.code == "unsupported_audio"


@pytest.mark.parametrize(
    ("status", "error"),
    [(404, MediaRefused), (403, MediaRefused), (503, MediaUnavailable), (429, MediaUnavailable)],
)
async def test_probe_errors_split_transient_from_permanent(status, error, caplog):
    def handler(request):
        return httpx.Response(404 if request.url.path == "/robots.txt" else status)

    async def resolve(host, port):
        return ["93.184.215.34"]

    fetcher = SafeFetcher(resolver=resolve, transport=httpx.MockTransport(handler))
    with pytest.raises(error) as err:
        await probe_audio(EP_URL, settings(), fetcher)
    if error is MediaRefused:
        assert err.value.code == "unsupported_audio"
    assert EP_URL not in caplog.text


async def test_probe_refuses_an_unsafe_address():
    async def resolve(host, port):
        return ["10.0.0.9"]

    fetcher = SafeFetcher(resolver=resolve, transport=httpx.MockTransport(lambda r: None))
    with pytest.raises(MediaRefused) as err:
        await probe_audio(EP_URL, settings(), fetcher)
    assert err.value.code == "unsupported_audio"
