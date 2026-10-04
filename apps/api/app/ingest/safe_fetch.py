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


@dataclass(frozen=True)
class FetchedPage:
    url: str  # final URL after redirects
    body: bytes
    encoding: str | None  # charset from Content-Type, if any


@dataclass(frozen=True)
class _Response:
    status: int
    content_type: str
    encoding: str | None
    body: bytes


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
        validate_url(url)
        if not await self.robots_allowed(url):
            raise FetchError("robots_disallowed", "the site's robots.txt disallows fetching")
        final_url, resp = await self._get(url, max_bytes=MAX_BODY_BYTES, types=content_types)
        if not 200 <= resp.status < 300:
            raise FetchError("upstream_error", f"site returned HTTP {resp.status}", resp.status)
        return FetchedPage(final_url, resp.body, resp.encoding)

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
        self, url: str, *, max_bytes: int, types: frozenset[str] | None
    ) -> tuple[str, _Response]:
        """GET with manual redirects; every hop re-validated and pinned. Returns final URL.

        `types` limits the accepted Content-Type of a 2xx response; None accepts any.
        """
        try:
            async with (
                asyncio.timeout(FETCH_TIMEOUT_S),
                httpx.AsyncClient(
                    transport=self.transport,
                    timeout=FETCH_TIMEOUT_S,
                    follow_redirects=False,
                    trust_env=False,  # never route through an env-configured proxy
                ) as client,
            ):
                current = url
                for _ in range(MAX_REDIRECTS + 1):
                    resp, location = await self._hop(client, current, max_bytes, types)
                    if location is None:
                        return current, resp
                    current = str(httpx.URL(current).join(location))
                raise FetchError("too_many_redirects", f"more than {MAX_REDIRECTS} redirects")
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise FetchError("timeout", f"fetch took longer than {FETCH_TIMEOUT_S:g}s") from exc
        except httpx.HTTPError as exc:
            raise FetchError("upstream_error", f"fetch failed: {type(exc).__name__}") from exc

    async def _hop(
        self,
        client: httpx.AsyncClient,
        url: str,
        max_bytes: int,
        types: frozenset[str] | None,
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
            body = await _read_capped(response, max_bytes)
            return _Response(
                response.status_code, content_type, response.charset_encoding, body
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
