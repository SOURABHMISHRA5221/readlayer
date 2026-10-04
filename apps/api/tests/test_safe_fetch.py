import httpx
import pytest

from app.ingest import safe_fetch as sf
from app.ingest.safe_fetch import FetchError, SafeFetcher

PUBLIC_IP = "93.184.215.34"
HTML = b"<html><body><p>Hello</p></body></html>"


def resolver(table: dict[str, list[str]]):
    async def resolve(host: str, port: int) -> list[str]:
        if host not in table:
            raise OSError("NXDOMAIN")
        return table[host]

    return resolve


class Site:
    """MockTransport keyed by the Host header; records every request it sees."""

    def __init__(self, routes: dict) -> None:
        self.routes = routes
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        route = self.routes.get((request.headers["host"], request.url.path))
        if route is None:
            return httpx.Response(404)
        return route(request) if callable(route) else route


def html(body: bytes = HTML, **headers) -> httpx.Response:
    return httpx.Response(200, content=body, headers={"content-type": "text/html", **headers})


def fetcher(routes, dns=None) -> tuple[SafeFetcher, Site]:
    site = Site(routes)
    dns = dns if dns is not None else {"news.example": [PUBLIC_IP]}
    return SafeFetcher(resolver=resolver(dns), transport=httpx.MockTransport(site.handler)), site


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://[::ffff:169.254.169.254]/",
        "http://[fe80::1]/",
        "http://[fd00:ec2::254]/",
        "http://10.0.0.5/",
        "http://192.168.1.1/",
        "http://100.64.0.1/",
        "http://0.0.0.0/",
        "http://[64:ff9b::7f00:1]/",  # NAT64 wrapping 127.0.0.1
        "http://[2002:7f00:1::]/",  # 6to4 wrapping 127.0.0.1
        "http://2130706433/",  # decimal 127.0.0.1
        "http://0x7f000001/",  # hex
        "http://0177.0.0.1/",  # octal
        "http://127.1/",  # short form
        "http://127.0.0.1./",  # trailing dot
        "ftp://news.example/",
        "file:///etc/passwd",
        "http://news.example:8080/",
        "https://news.example:22/",
        "http://user:pass@news.example/",
    ],
)
async def test_unsafe_urls_rejected_without_a_request(url):
    f, site = fetcher({})
    with pytest.raises(FetchError) as err:
        await f.fetch(url)
    assert err.value.code == "unsafe_url"
    assert site.requests == []


@pytest.mark.parametrize(
    "answers",
    [["10.1.2.3"], [PUBLIC_IP, "10.1.2.3"], ["::1"], ["169.254.169.254"], ["::ffff:10.0.0.1"]],
)
async def test_hostname_resolving_to_internal_ip_rejected(answers):
    f, site = fetcher({}, dns={"evil.example": answers})
    with pytest.raises(FetchError) as err:
        await f.fetch("http://evil.example/")
    assert err.value.code == "unsafe_url"
    assert site.requests == []


async def test_public_page_fetched_and_connection_pinned_to_checked_ip():
    f, site = fetcher({("news.example", "/story"): html()})
    page = await f.fetch("https://news.example/story?id=1")
    assert page.body == HTML and page.url == "https://news.example/story?id=1"
    req = site.requests[-1]
    assert req.url.host == PUBLIC_IP  # socket goes to the IP we checked
    assert req.headers["host"] == "news.example"
    assert req.extensions["sni_hostname"] == "news.example"  # TLS verifies the real name
    assert req.headers["user-agent"].startswith("ReadLayerBot")


async def test_redirect_to_internal_ip_rejected():
    f, site = fetcher(
        {
            ("news.example", "/a"): httpx.Response(
                302, headers={"location": "http://169.254.169.254/latest/"}
            )
        }
    )
    with pytest.raises(FetchError) as err:
        await f.fetch("http://news.example/a")
    assert err.value.code == "unsafe_url"
    assert all(r.url.host == PUBLIC_IP for r in site.requests)


async def test_redirect_to_host_resolving_internal_rejected():
    f, _ = fetcher(
        {("news.example", "/a"): httpx.Response(301, headers={"location": "http://in.example/"})},
        dns={"news.example": [PUBLIC_IP], "in.example": ["10.9.9.9"]},
    )
    with pytest.raises(FetchError) as err:
        await f.fetch("http://news.example/a")
    assert err.value.code == "unsafe_url"


async def test_relative_redirect_followed_and_rechecked():
    f, site = fetcher(
        {
            ("news.example", "/a"): httpx.Response(301, headers={"location": "/b"}),
            ("news.example", "/b"): html(),
        }
    )
    page = await f.fetch("http://news.example/a")
    assert page.url == "http://news.example/b"


async def test_more_than_three_redirects_rejected():
    routes = {
        ("news.example", f"/{i}"): httpx.Response(302, headers={"location": f"/{i + 1}"})
        for i in range(5)
    }
    f, _ = fetcher(routes)
    with pytest.raises(FetchError) as err:
        await f.fetch("http://news.example/0")
    assert err.value.code == "too_many_redirects"


async def test_three_redirects_allowed():
    routes = {
        ("news.example", f"/{i}"): httpx.Response(302, headers={"location": f"/{i + 1}"})
        for i in range(3)
    }
    routes[("news.example", "/3")] = html()
    f, _ = fetcher(routes)
    assert (await f.fetch("http://news.example/0")).url == "http://news.example/3"


async def test_non_html_rejected():
    f, _ = fetcher(
        {
            ("news.example", "/f.pdf"): httpx.Response(
                200, headers={"content-type": "application/pdf"}
            )
        }
    )
    with pytest.raises(FetchError) as err:
        await f.fetch("http://news.example/f.pdf")
    assert err.value.code == "not_html"


async def test_declared_oversize_body_rejected():
    big = html(b"x", **{"content-length": str(sf.MAX_BODY_BYTES + 1)})
    f, _ = fetcher({("news.example", "/big"): big})
    with pytest.raises(FetchError) as err:
        await f.fetch("http://news.example/big")
    assert err.value.code == "too_large"


async def test_streamed_oversize_body_rejected():
    async def stream():
        for _ in range(4):
            yield b"x" * (1024 * 1024)

    resp = httpx.Response(200, headers={"content-type": "text/html"}, content=stream())
    f, _ = fetcher({("news.example", "/big"): resp})
    with pytest.raises(FetchError) as err:
        await f.fetch("http://news.example/big")
    assert err.value.code == "too_large"


async def test_robots_disallow_respected():
    robots = httpx.Response(
        200,
        text="User-agent: ReadLayerBot\nDisallow: /private\n",
        headers={"content-type": "text/plain"},
    )
    f, site = fetcher(
        {("news.example", "/robots.txt"): robots, ("news.example", "/private/x"): html()}
    )
    with pytest.raises(FetchError) as err:
        await f.fetch("http://news.example/private/x")
    assert err.value.code == "robots_disallowed"
    assert [r.url.path for r in site.requests] == ["/robots.txt"]


async def test_missing_robots_allows_and_is_cached():
    f, site = fetcher({("news.example", "/a"): html(), ("news.example", "/b"): html()})
    await f.fetch("http://news.example/a")
    await f.fetch("http://news.example/b")
    assert [r.url.path for r in site.requests] == ["/robots.txt", "/a", "/b"]


async def test_upstream_error_status_reported():
    f, _ = fetcher({("news.example", "/gone"): httpx.Response(410)})
    with pytest.raises(FetchError) as err:
        await f.fetch("http://news.example/gone")
    assert err.value.code == "upstream_error"


async def test_timeout_mapped():
    def slow(request):
        raise httpx.ReadTimeout("slow", request=request)

    f, _ = fetcher(
        {("news.example", "/robots.txt"): httpx.Response(404), ("news.example", "/s"): slow}
    )
    with pytest.raises(FetchError) as err:
        await f.fetch("http://news.example/s")
    assert err.value.code == "timeout"


@pytest.mark.parametrize(
    ("ip", "public"),
    [
        ("8.8.8.8", True),
        ("2606:4700:4700::1111", True),
        ("::ffff:8.8.8.8", True),
        ("::ffff:10.0.0.1", False),
        ("224.0.0.1", False),
        ("240.0.0.1", False),
        ("::", False),
    ],
)
def test_is_public_ip(ip, public):
    import ipaddress

    assert sf.is_public_ip(ipaddress.ip_address(ip)) is public
