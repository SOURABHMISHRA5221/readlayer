"""Audio through the SSRF guard: ranged head at open, whole file at transcribe (Media plan §B,
Round 5 5.3, 5.4, 5R1, 5R2, 5R5, 5R10, 5R11)."""

import httpx
import pytest

from app.ingest import safe_fetch as sf
from app.ingest.safe_fetch import FetchError
from tests.test_safe_fetch import PUBLIC_IP, fetcher

HOST = "cdn.example"
DNS = {HOST: [PUBLIC_IP], "track.example": [PUBLIC_IP], "inside.example": ["10.0.0.7"]}
MB = 1_000_000


def audio_fetcher(routes):
    routes = {(HOST, "/robots.txt"): httpx.Response(404), **routes}
    return fetcher(routes, dns=DNS)


class Body:
    """A streamed body that counts how much of it was pulled."""

    def __init__(self, size: int, chunk: int = 64 * 1024, fill: int = 0x41) -> None:
        self.size, self.chunk, self.fill, self.sent = size, chunk, fill, 0

    async def __aiter__(self):
        while self.sent < self.size:
            n = min(self.chunk, self.size - self.sent)
            self.sent += n
            yield bytes([self.fill]) * n


def mp3_response(status: int = 200, body=b"\xff\xfb" * 10, **headers) -> httpx.Response:
    return httpx.Response(status, content=body, headers={"content-type": "audio/mpeg", **headers})


# --- head ------------------------------------------------------------------------------------


async def test_head_on_206_reads_total_from_content_range():
    seen = {}

    def ranged(request):
        seen.update(request.headers)
        return mp3_response(
            206, body=b"\xff" * 65536, **{"content-range": "bytes 0-65535/48000000"}
        )

    f, site = audio_fetcher({(HOST, "/ep.mp3"): ranged})
    head = await f.audio_head(f"https://{HOST}/ep.mp3")
    assert head.total_bytes == 48 * MB
    assert head.start == 0
    assert len(head.data) == 65536
    assert head.final_url == f"https://{HOST}/ep.mp3"
    assert seen["range"] == "bytes=0-65535"
    assert seen["accept"].startswith("audio/mpeg")
    assert site.requests[-1].url.host == PUBLIC_IP  # pinned like pages


async def test_head_on_200_stops_after_64kb_and_uses_content_length():
    # 5R2: a host that ignores Range streams the whole file; we read 64 KB and close.
    body = Body(50 * MB)
    resp = mp3_response(200, body=body, **{"content-length": str(50 * MB)})
    f, _ = audio_fetcher({(HOST, "/ep.mp3"): resp})
    head = await f.audio_head(f"https://{HOST}/ep.mp3")
    assert head.total_bytes == 50 * MB
    assert len(head.data) == sf.AUDIO_HEAD_BYTES
    assert body.sent < 1 * MB


async def test_head_at_an_offset_on_206():
    # 5R1: the second probe after a big ID3 tag asks for 16 KB at the tag's end.
    seen = {}

    def ranged(request):
        seen.update(request.headers)
        return mp3_response(
            206, body=b"\xff" * 16384, **{"content-range": "bytes 1000010-1016393/48000000"}
        )

    f, _ = audio_fetcher({(HOST, "/ep.mp3"): ranged})
    head = await f.audio_head(f"https://{HOST}/ep.mp3", start=1_000_010, length=16384)
    assert seen["range"] == "bytes=1000010-1016393"
    assert head.start == 1_000_010 and len(head.data) == 16384


async def test_head_at_an_offset_on_200_skips_to_the_offset():
    async def body():
        yield b"\x00" * 1_000_000
        yield b"\xff" * 100_000

    resp = mp3_response(200, body=body(), **{"content-length": "1100000"})
    f, _ = audio_fetcher({(HOST, "/ep.mp3"): resp})
    head = await f.audio_head(f"https://{HOST}/ep.mp3", start=1_000_000, length=16384)
    assert head.start == 1_000_000
    assert head.data == b"\xff" * 16384


async def test_head_206_for_the_wrong_range_is_an_error():
    resp = mp3_response(206, **{"content-range": "bytes 500-1000/48000000"})
    f, _ = audio_fetcher({(HOST, "/ep.mp3"): resp})
    with pytest.raises(FetchError) as err:
        await f.audio_head(f"https://{HOST}/ep.mp3")
    assert err.value.code == "upstream_error" and not sf.is_transient(err.value)


@pytest.mark.parametrize(
    ("status", "headers", "total"),
    [
        (206, {"content-range": "bytes 0-65535/*"}, None),
        (206, {}, None),
        (200, {}, None),  # streamed, so no Content-Length
    ],
)
async def test_head_unknown_total(status, headers, total):
    resp = mp3_response(status, body=Body(100), **headers)
    f, _ = audio_fetcher({(HOST, "/ep.mp3"): resp})
    assert (await f.audio_head(f"https://{HOST}/ep.mp3")).total_bytes == total


@pytest.mark.parametrize("ctype", ["audio/mpeg", "audio/mp3", "Audio/MPEG; charset=binary"])
async def test_head_accepts_mp3_types(ctype):
    resp = httpx.Response(200, content=b"\xff\xfb", headers={"content-type": ctype})
    f, _ = audio_fetcher({(HOST, "/ep.mp3"): resp})
    await f.audio_head(f"https://{HOST}/ep.mp3")


@pytest.mark.parametrize("ctype", ["audio/mp4", "audio/x-m4a", "text/html", ""])
async def test_head_refuses_other_types(ctype):
    resp = httpx.Response(200, content=b"x", headers={"content-type": ctype})
    f, _ = audio_fetcher({(HOST, "/ep.mp3"): resp})
    with pytest.raises(FetchError) as err:
        await f.audio_head(f"https://{HOST}/ep.mp3")
    assert err.value.code == "not_html"  # the guard's wrong-type code
    assert not sf.is_transient(err.value)


async def test_six_redirects_allowed_seven_refused():
    hops = {
        (HOST, f"/{i}"): httpx.Response(302, headers={"location": f"/{i + 1}"}) for i in range(7)
    }
    hops[(HOST, "/6")] = mp3_response()
    f, _ = audio_fetcher(hops)
    assert (await f.audio_head(f"https://{HOST}/0")).final_url == f"https://{HOST}/6"

    hops[(HOST, "/6")] = httpx.Response(302, headers={"location": "/7"})
    hops[(HOST, "/7")] = mp3_response()
    f, _ = audio_fetcher(hops)
    with pytest.raises(FetchError) as err:
        await f.audio_head(f"https://{HOST}/0")
    assert err.value.code == "too_many_redirects"


async def test_measurement_prefix_redirect_to_another_host_followed():
    routes = {
        ("track.example", "/robots.txt"): httpx.Response(404),
        ("track.example", "/p/cdn.example/ep.mp3"): httpx.Response(
            302, headers={"location": f"https://{HOST}/ep.mp3"}
        ),
        (HOST, "/ep.mp3"): mp3_response(),
    }
    f, _ = audio_fetcher(routes)
    head = await f.audio_head("https://track.example/p/cdn.example/ep.mp3")
    assert head.final_url == f"https://{HOST}/ep.mp3"


async def test_redirect_to_internal_host_refused():
    routes = {
        (HOST, "/ep.mp3"): httpx.Response(302, headers={"location": "https://inside.example/a"})
    }
    f, _ = audio_fetcher(routes)
    for call in (f.audio_head, lambda u: f.fetch_audio(u, max_bytes=MB)):
        with pytest.raises(FetchError) as err:
            await call(f"https://{HOST}/ep.mp3")
        assert err.value.code == "unsafe_url" and not sf.is_transient(err.value)


async def test_robots_disallow_respected_for_audio():
    robots = httpx.Response(
        200, text="User-agent: *\nDisallow: /\n", headers={"content-type": "text/plain"}
    )
    f, site = audio_fetcher({(HOST, "/robots.txt"): robots, (HOST, "/ep.mp3"): mp3_response()})
    for call in (f.audio_head, lambda u: f.fetch_audio(u, max_bytes=MB)):
        with pytest.raises(FetchError) as err:
            await call(f"https://{HOST}/ep.mp3")
        assert err.value.code == "robots_disallowed"
    assert all(r.url.path == "/robots.txt" for r in site.requests)


# --- transient vs permanent (5R5) ------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "transient"),
    [(500, True), (503, True), (429, True), (401, False), (403, False), (404, False),
     (410, False), (416, False)],
)  # fmt: skip
async def test_status_errors_classified(status, transient):
    f, _ = audio_fetcher({(HOST, "/ep.mp3"): httpx.Response(status)})
    for call in (f.audio_head, lambda u: f.fetch_audio(u, max_bytes=MB)):
        with pytest.raises(FetchError) as err:
            await call(f"https://{HOST}/ep.mp3")
        assert err.value.status == status
        assert sf.is_transient(err.value) is transient


@pytest.mark.parametrize(
    "exc",
    [httpx.ReadTimeout("slow"), httpx.ConnectError("refused"), httpx.RemoteProtocolError("x")],
)
async def test_network_errors_are_transient(exc):
    def fail(request):
        raise exc

    f, _ = audio_fetcher({(HOST, "/ep.mp3"): fail})
    with pytest.raises(FetchError) as err:
        await f.audio_head(f"https://{HOST}/ep.mp3")
    assert sf.is_transient(err.value)


def test_too_large_and_unsafe_are_permanent():
    for code in ("too_large", "unsafe_url", "robots_disallowed", "too_many_redirects"):
        assert not sf.is_transient(FetchError(code, "x"))
    assert sf.is_transient(FetchError("upstream_error", "host could not be resolved"))


# --- whole file ------------------------------------------------------------------------------


async def test_fetch_audio_reads_everything_into_one_bytearray():
    body = Body(3 * MB, chunk=100_003)
    resp = mp3_response(200, body=body, **{"content-length": str(3 * MB)})
    f, site = audio_fetcher({(HOST, "/ep.mp3"): resp})
    got = await f.fetch_audio(f"https://{HOST}/ep.mp3", max_bytes=70 * MB, expected_bytes=3 * MB)
    assert isinstance(got.body, bytearray)
    assert got.body == b"A" * (3 * MB)
    assert got.final_url == f"https://{HOST}/ep.mp3"
    assert "range" not in site.requests[-1].headers


@pytest.mark.parametrize("expected", [None, 1 * MB, 5 * MB])
async def test_fetch_audio_when_the_expected_size_is_wrong(expected):
    # Preallocated from the head's total (5R10); the body may still be shorter or longer.
    resp = mp3_response(200, body=Body(3 * MB, chunk=77_777))
    f, _ = audio_fetcher({(HOST, "/ep.mp3"): resp})
    got = await f.fetch_audio(f"https://{HOST}/ep.mp3", max_bytes=70 * MB, expected_bytes=expected)
    assert len(got.body) == 3 * MB and got.body == b"A" * (3 * MB)


async def test_fetch_audio_cut_off_mid_stream():
    body = Body(8 * MB)
    f, _ = audio_fetcher({(HOST, "/ep.mp3"): mp3_response(200, body=body)})
    with pytest.raises(FetchError) as err:
        await f.fetch_audio(f"https://{HOST}/ep.mp3", max_bytes=5 * MB)
    assert err.value.code == "too_large" and not sf.is_transient(err.value)
    assert body.sent <= 5 * MB + body.chunk


async def test_fetch_audio_declared_oversize_refused_before_reading():
    body = Body(8 * MB)
    resp = mp3_response(200, body=body, **{"content-length": str(8 * MB)})
    f, _ = audio_fetcher({(HOST, "/ep.mp3"): resp})
    with pytest.raises(FetchError) as err:
        await f.fetch_audio(f"https://{HOST}/ep.mp3", max_bytes=5 * MB)
    assert err.value.code == "too_large"
    assert body.sent == 0


async def test_fetch_audio_refuses_other_types():
    resp = httpx.Response(200, content=b"<html>", headers={"content-type": "text/html"})
    f, _ = audio_fetcher({(HOST, "/ep.mp3"): resp})
    with pytest.raises(FetchError) as err:
        await f.fetch_audio(f"https://{HOST}/ep.mp3", max_bytes=MB)
    assert err.value.code == "not_html"


async def test_error_bodies_are_not_read_into_the_audio_buffer():
    body = Body(8 * MB)
    f, _ = audio_fetcher({(HOST, "/ep.mp3"): httpx.Response(503, content=body)})
    with pytest.raises(FetchError):
        await f.fetch_audio(f"https://{HOST}/ep.mp3", max_bytes=5 * MB)
    assert body.sent <= body.chunk
