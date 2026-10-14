"""The only way the API fetches a user-supplied URL (DESIGN §11.2, SSRF guard).

Every hop (initial request and each redirect) is validated, its host resolved, and every
resolved address must be public. The socket then connects to the checked IP while TLS SNI,
certificate verification and the Host header use the original hostname, so a DNS answer that
changes between check and connect (rebinding) cannot redirect the connection.
"""

import asyncio
import ipaddress
import logging
import re
import socket
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Literal
from urllib.robotparser import RobotFileParser

import httpx

log = logging.getLogger("app.ingest.fetch")

USER_AGENT = "ReadLayerBot/0.1 (+https://github.com/readlayer; personalized reading overlay)"
ROBOTS_AGENT = "ReadLayerBot"
ALLOWED_SCHEMES = {"http": 80, "https": 443}
MAX_REDIRECTS = 3
FETCH_TIMEOUT_S = 10.0
MAX_BODY_BYTES = 3 * 1024 * 1024
MAX_ROBOTS_BYTES = 500 * 1024
ROBOTS_TTL_S = 3600.0
HTML_TYPES = frozenset({"text/html", "application/xhtml+xml"})
REDIRECT_STATUSES = {301, 302, 303, 307, 308}

# Podcast audio (Media plan §B): enclosures chain measurement prefixes before the CDN.
MAX_AUDIO_REDIRECTS = 6
AUDIO_TIMEOUT_S = 45.0
AUDIO_HEAD_BYTES = 64 * 1024
AUDIO_TYPES = frozenset({"audio/mpeg", "audio/mp3"})
AUDIO_ACCEPT = "audio/mpeg,*/*;q=0.1"
_CONTENT_RANGE = re.compile(r"^bytes (\d+)-\d+/(\d+|\*)$")

# Ranges `is_global` doesn't already exclude, or that we want named explicitly.
_BLOCKED_NETS = [
    ipaddress.ip_network(n)
    for n in (
        "169.254.0.0/16",  # link-local, incl. the 169.254.169.254 metadata server
        "100.64.0.0/10",  # carrier-grade NAT
        "fd00:ec2::254/128",  # AWS IPv6 metadata
        "2001::/32",  # Teredo: tunnels to an arbitrary IPv4
    )
]
_NAT64 = ipaddress.ip_network("64:ff9b::/96")
_NUMERIC_LABEL = re.compile(r"^(0x[0-9a-f]*|[0-9]+)$")

FetchErrorCode = Literal[
    "unsafe_url",
    "robots_disallowed",
    "not_html",
    "too_large",
    "too_many_redirects",
    "timeout",
    "upstream_error",
    "no_article_text",
]


class FetchError(Exception):
    def __init__(self, code: FetchErrorCode, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status  # upstream HTTP status, when the failure was one


IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
Resolver = Callable[[str, int], Awaitable[list[str]]]
BodyReader = Callable[[httpx.Response], Awaitable[bytes | bytearray]]


@dataclass(frozen=True)
class FetchedPage:
    url: str  # final URL after redirects
    body: bytes
    encoding: str | None  # charset from Content-Type, if any


@dataclass(frozen=True)
class AudioHead:
    """The opening bytes of an audio file (or `length` bytes from `start`) and its size."""

    final_url: str
    start: int
    total_bytes: int | None  # None when the host didn't say
    data: bytes


@dataclass(frozen=True)
class FetchedAudio:
    final_url: str
    body: bytearray  # lives only for the transcribe request; never stored or logged


@dataclass(frozen=True)
class _Response:
    status: int
    content_type: str
    encoding: str | None
    body: bytes | bytearray
    headers: httpx.Headers = field(default_factory=httpx.Headers)


# ---------------------------------------------------------------- URL and IP checks


def is_public_ip(ip: IPAddress) -> bool:
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        elif ip.sixtofour is not None:
            ip = ip.sixtofour
        elif ip in _NAT64:
            ip = ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    if any(ip.version == net.version and ip in net for net in _BLOCKED_NETS):
        return False
    return ip.is_global and not (
        ip.is_multicast
        or ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_unspecified
    )


def validate_url(url: str) -> httpx.URL:
    """Scheme, port and host-shape checks that need no DNS."""
    try:
        parsed = httpx.URL(url)
    except Exception as exc:
        raise FetchError("unsafe_url", "URL could not be parsed") from exc
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise FetchError("unsafe_url", "only http and https URLs are allowed")
    if parsed.port is not None and parsed.port != ALLOWED_SCHEMES[parsed.scheme]:
        raise FetchError("unsafe_url", "only ports 80 and 443 are allowed")
    if parsed.userinfo:
        raise FetchError("unsafe_url", "URLs with credentials are not allowed")
    host = parsed.host.rstrip(".").lower()
    if not host:
        raise FetchError("unsafe_url", "URL has no host")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None and not is_public_ip(literal):
        raise FetchError("unsafe_url", "URL points to a private or reserved address")
    if literal is None and ":" not in host:
        labels = host.split(".")
        # All-numeric hosts must be a canonical dotted quad. Decimal (2130706433), hex
        # (0x7f000001), octal (0177.0.0.1) and short (127.1) forms resolve to IPs via libc.
        if all(_NUMERIC_LABEL.match(label) for label in labels):
            try:
                canonical = str(ipaddress.IPv4Address(host)) == host
            except ValueError:
                canonical = False
            if not canonical:
                raise FetchError("unsafe_url", "non-canonical numeric host")
    return parsed


async def system_resolver(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


# ---------------------------------------------------------------- fetcher


@dataclass
class SafeFetcher:
    resolver: Resolver = system_resolver
    transport: httpx.AsyncBaseTransport | None = None  # injected in tests
    _robots: dict[str, tuple[float, RobotFileParser | None]] = field(default_factory=dict)

    async def fetch(self, url: str, *, content_types: frozenset[str] = HTML_TYPES) -> FetchedPage:
        """Fetch a page of one of `content_types` (HTML by default), honouring robots.txt.

        Raises FetchError. Scripts pass XML/JSON types for feeds and public APIs so every
        outbound fetch goes through the same guard.
        """
        await self._check_allowed(url)
        final_url, resp = await self._get(url, max_bytes=MAX_BODY_BYTES, types=content_types)
        _require_ok(resp)
        return FetchedPage(final_url, bytes(resp.body), resp.encoding)

    async def audio_head(
        self, url: str, *, start: int = 0, length: int = AUDIO_HEAD_BYTES
    ) -> AudioHead:
        """`length` bytes of an MP3 from `start`, by a ranged GET, and the file's total size.

        A host that ignores Range answers 200 with the whole file: the stream is read up to
        what was asked for and closed (5R2). Raises FetchError; `is_transient` sorts it.
        """
        await self._check_allowed(url)

        async def read(response: httpx.Response) -> bytes:
            skip = 0 if response.status_code == 206 else start
            return await _read_window(response, skip, length)

        final_url, resp = await self._get(
            url,
            max_bytes=length,
            types=AUDIO_TYPES,
            max_redirects=MAX_AUDIO_REDIRECTS,
            headers={"Range": f"bytes={start}-{start + length - 1}", "Accept": AUDIO_ACCEPT},
            read=read,
        )
        _require_ok(resp)
        served, total = _audio_extent(resp)
        if served is not None and served != start:
            raise FetchError("upstream_error", "host sent a different byte range", resp.status)
        return AudioHead(final_url, start, total, bytes(resp.body))

    async def fetch_audio(
        self, url: str, *, max_bytes: int, expected_bytes: int | None = None
    ) -> FetchedAudio:
        """The whole MP3, read into one buffer preallocated from `expected_bytes` (the head's
        total) and cut off past `max_bytes`. Raises FetchError."""
        await self._check_allowed(url)
        final_url, resp = await self._get(
            url,
            max_bytes=max_bytes,
            types=AUDIO_TYPES,
            max_redirects=MAX_AUDIO_REDIRECTS,
            timeout_s=AUDIO_TIMEOUT_S,
            headers={"Accept": AUDIO_ACCEPT},
            read=lambda response: _read_into(response, max_bytes, expected_bytes),
        )
        _require_ok(resp)
        assert isinstance(resp.body, bytearray)
        return FetchedAudio(final_url, resp.body)

    async def _check_allowed(self, url: str) -> None:
        validate_url(url)
        if not await self.robots_allowed(url):
            raise FetchError("robots_disallowed", "the site's robots.txt disallows fetching")

    async def robots_allowed(self, url: str) -> bool:
        parsed = httpx.URL(url)
        origin = f"{parsed.scheme}://{parsed.netloc.decode()}"
        cached = self._robots.get(origin)
        if cached is None or time.monotonic() - cached[0] > ROBOTS_TTL_S:
            cached = (time.monotonic(), await self._load_robots(origin))
            self._robots[origin] = cached
        parser = cached[1]
        return parser is None or parser.can_fetch(ROBOTS_AGENT, url)

    async def _load_robots(self, origin: str) -> RobotFileParser | None:
        """None means no usable rules: allow."""
        try:
            _, resp = await self._get(
                f"{origin}/robots.txt", max_bytes=MAX_ROBOTS_BYTES, types=None
            )
        except FetchError as exc:
            if exc.code == "unsafe_url":
                raise
            log.warning("robots.txt unavailable, allowing", extra={"error_code": exc.code})
            return None
        if 400 <= resp.status < 500:
            return None
        if resp.status >= 500:
            log.warning("robots.txt server error, allowing", extra={"status": resp.status})
            return None
        parser = RobotFileParser()
        parser.parse(resp.body.decode(resp.encoding or "utf-8", errors="replace").splitlines())
        return parser

    async def _get(
        self,
        url: str,
        *,
        max_bytes: int,
        types: frozenset[str] | None,
        max_redirects: int = MAX_REDIRECTS,
        timeout_s: float = FETCH_TIMEOUT_S,
        headers: dict[str, str] | None = None,
        read: BodyReader | None = None,
    ) -> tuple[str, _Response]:
        """GET with manual redirects; every hop re-validated and pinned. Returns final URL.

        `types` limits the accepted Content-Type of a 2xx response; None accepts any. `read`
        replaces the capped body read for a 2xx response; other bodies are then not read.
        """
        try:
            async with (
                asyncio.timeout(timeout_s),
                httpx.AsyncClient(
                    transport=self.transport,
                    timeout=timeout_s,
                    follow_redirects=False,
                    trust_env=False,  # never route through an env-configured proxy
                ) as client,
            ):
                current = url
                for _ in range(max_redirects + 1):
                    resp, location = await self._hop(
                        client, current, max_bytes, types, headers or {}, read
                    )
                    if location is None:
                        return current, resp
                    current = str(httpx.URL(current).join(location))
                raise FetchError("too_many_redirects", f"more than {max_redirects} redirects")
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise FetchError("timeout", f"fetch took longer than {timeout_s:g}s") from exc
        except httpx.HTTPError as exc:
            raise FetchError("upstream_error", f"fetch failed: {type(exc).__name__}") from exc

    async def _hop(
        self,
        client: httpx.AsyncClient,
        url: str,
        max_bytes: int,
        types: frozenset[str] | None,
        extra_headers: dict[str, str],
        read: BodyReader | None,
    ) -> tuple[_Response, str | None]:
        parsed = validate_url(url)
        host = parsed.host.rstrip(".").lower()
        port = parsed.port or ALLOWED_SCHEMES[parsed.scheme]
        ip = await self._checked_ip(host, port)
        request = client.build_request(
            "GET",
            parsed.copy_with(host=str(ip)),
            headers={
                "Host": parsed.netloc.decode(),
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
                **extra_headers,
            },
            extensions={"sni_hostname": host},
        )
        response = await client.send(request, stream=True)
        try:
            if response.status_code in REDIRECT_STATUSES:
                location = response.headers.get("location")
                if not location:
                    raise FetchError("upstream_error", "redirect without a Location header")
                return _Response(response.status_code, "", None, b""), location
            content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
            ok = 200 <= response.status_code < 300
            if ok and types is not None and content_type not in types:
                wanted = "an HTML page" if types == HTML_TYPES else "/".join(sorted(types))
                raise FetchError("not_html", f"expected {wanted}, got {content_type or '?'}")
            if read is None:
                body: bytes | bytearray = await _read_capped(response, max_bytes)
            else:
                body = await read(response) if ok else b""
            return _Response(
                response.status_code,
                content_type,
                response.charset_encoding,
                body,
                response.headers,
            ), None
        finally:
            await response.aclose()

    async def _checked_ip(self, host: str, port: int) -> IPAddress:
        try:
            literal = ipaddress.ip_address(host)
        except ValueError:
            literal = None
        if literal is not None:
            addresses = [literal]
        else:
            try:
                resolved = await self.resolver(host, port)
            except OSError as exc:
                raise FetchError("upstream_error", "host could not be resolved") from exc
            addresses = [ipaddress.ip_address(a.split("%", 1)[0]) for a in resolved]
        if not addresses:
            raise FetchError("upstream_error", "host could not be resolved")
        # Reject if ANY answer is internal: an attacker controls which one the client picks.
        if not all(is_public_ip(a) for a in addresses):
            log.warning("blocked non-public address", extra={"host": host})
            raise FetchError("unsafe_url", "URL points to a private or reserved address")
        return addresses[0]


def _require_ok(resp: _Response) -> None:
    if not 200 <= resp.status < 300:
        raise FetchError("upstream_error", f"site returned HTTP {resp.status}", resp.status)


def is_transient(exc: FetchError) -> bool:
    """Worth retrying later: a timeout, a connection failure, 5xx or 429 (5R5). Anything else
    (wrong type, too big, robots, unsafe address, other 4xx) will fail the same way again."""
    if exc.code == "timeout":
        return True
    if exc.code != "upstream_error":
        return False
    return exc.status is None or exc.status == 429 or exc.status >= 500


def _audio_extent(resp: _Response) -> tuple[int | None, int | None]:
    """(first byte served, total size) from Content-Range on a 206, Content-Length on a 200."""
    if resp.status == 206:
        match = _CONTENT_RANGE.match(resp.headers.get("content-range", "").strip())
        if match is None:
            return None, None
        total = match.group(2)
        return int(match.group(1)), None if total == "*" else int(total)
    declared = resp.headers.get("content-length", "")
    return None, int(declared) if declared.isdigit() else None


async def _read_window(response: httpx.Response, skip: int, limit: int) -> bytes:
    """Bytes [skip, skip + limit) of the stream; stops reading once it has them."""
    buf = bytearray()
    seen = 0
    async for chunk in response.aiter_bytes():
        begin = max(0, skip - seen)
        seen += len(chunk)
        if begin >= len(chunk):
            continue
        buf += chunk[begin : begin + limit - len(buf)]
        if len(buf) >= limit:
            break
    return bytes(buf)


async def _read_into(
    response: httpx.Response, max_bytes: int, expected_bytes: int | None
) -> bytearray:
    """The whole body in one bytearray (no chunk list, so 70 MB stays ~70 MB), preallocated
    from `expected_bytes`, else the declared Content-Length, and grown only if the body is
    longer (5R10)."""
    declared = response.headers.get("content-length")
    length = int(declared) if declared and declared.isdigit() else None
    if length is not None and length > max_bytes:
        raise FetchError("too_large", f"audio is larger than {max_bytes // 1_000_000} MB")
    buf = bytearray(min(expected_bytes or length or 0, max_bytes))
    size = 0
    async for chunk in response.aiter_bytes():
        end = size + len(chunk)
        if end > max_bytes:
            raise FetchError("too_large", f"audio is larger than {max_bytes // 1_000_000} MB")
        if end <= len(buf):
            buf[size:end] = chunk
        else:
            del buf[size:]
            buf += chunk
        size = end
    del buf[size:]
    return buf


async def _read_capped(response: httpx.Response, max_bytes: int) -> bytes:
    declared = response.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > max_bytes:
        raise FetchError("too_large", f"page is larger than {max_bytes // (1024 * 1024)} MB")
    chunks: list[bytes] = []
    size = 0
    async for chunk in response.aiter_bytes():
        size += len(chunk)
        if size > max_bytes:
            raise FetchError("too_large", f"page is larger than {max_bytes // (1024 * 1024)} MB")
        chunks.append(chunk)
    return b"".join(chunks)


# ---------------------------------------------------------------- module default

_fetcher: SafeFetcher | None = None


def get_fetcher() -> SafeFetcher:
    global _fetcher
    if _fetcher is None:
        _fetcher = SafeFetcher()
    return _fetcher


def set_fetcher(fetcher: SafeFetcher | None) -> None:
    global _fetcher
    _fetcher = fetcher


async def safe_fetch(url: str) -> FetchedPage:
    return await get_fetcher().fetch(url)
