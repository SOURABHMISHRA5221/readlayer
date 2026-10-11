"""Outlet registry for the For you feed (decision 50, DESIGN §17). Data and pure helpers only.

Articles come from top outlets' section feeds, collected twice a day by a job that knows no
reader. A reader's country decides which outlets count as "local" (their country's own) and
which as "global"; the feed mixes 60% local / 40% global. Every feed here was checked through
our own `safe_fetch` (2026-10-11) and every outlet measured readable (`scripts/check_outlets.py`,
`docs/evidence/d50/outlets.txt`). Topics an outlet has no section for map to its closest one.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

Country = Literal["IN", "GB", "US", "other"]
COUNTRIES: tuple[Country, ...] = ("IN", "GB", "US", "other")
Side = Literal["local", "global"]
LOCAL_SHARE = 0.6
# Global wires a restricted search fallback may also return (always "global").
WIRE_HOSTS = ("reuters.com", "apnews.com")


@dataclass(frozen=True)
class Outlet:
    id: str
    name: str
    home: Literal["IN", "GB", "US"]  # its own country
    region: Literal["global", "IN"]  # "global": offered to readers everywhere
    feed_hosts: tuple[str, ...]
    article_hosts: tuple[str, ...]
    sections: Mapping[str, tuple[str, ...]]  # taxonomy domain → section feed URLs


def _bbc(*paths: str) -> tuple[str, ...]:
    return tuple(f"https://feeds.bbci.co.uk/{p}/rss.xml" for p in paths)


def _guardian(*paths: str) -> tuple[str, ...]:
    return tuple(f"https://www.theguardian.com/{p}/rss" for p in paths)


def _npr(*ids: int) -> tuple[str, ...]:
    return tuple(f"https://feeds.npr.org/{i}/rss.xml" for i in ids)


def _hindu(*paths: str) -> tuple[str, ...]:
    return tuple(f"https://www.thehindu.com/{p}/feeder/default.rss" for p in paths)


def _express(*paths: str) -> tuple[str, ...]:
    return tuple(f"https://indianexpress.com/section/{p}/feed/" for p in paths)


def _mint(*paths: str) -> tuple[str, ...]:
    return tuple(f"https://www.livemint.com/rss/{p}" for p in paths)


def _et(*paths: str) -> tuple[str, ...]:
    return tuple(f"https://economictimes.indiatimes.com/{p}" for p in paths)


REGISTRY: tuple[Outlet, ...] = (
    Outlet("bbc", "BBC", "GB", "global", ("feeds.bbci.co.uk",), ("bbc.co.uk", "bbc.com"), {
        "economics": _bbc("news/business/economy"),
        "finance": _bbc("news/business"),
        "business": _bbc("news/business"),
        "policy": _bbc("news/politics"),
        "politics": _bbc("news/politics", "news/world"),
        "technology": _bbc("news/technology"),
        "science": _bbc("news/science_and_environment"),
        "health": _bbc("news/health"),
        "environment": _bbc("news/science_and_environment"),
        "sports": _bbc("sport"),
        "culture": _bbc("news/entertainment_and_arts"),
        "education": _bbc("news/education"),
    }),
    Outlet("guardian", "The Guardian", "GB", "global", ("theguardian.com",), ("theguardian.com",), {
        "economics": _guardian("business/economics"),
        "finance": _guardian("business/stock-markets"),
        "business": _guardian("business"),
        "policy": _guardian("politics"),
        "politics": _guardian("politics", "world"),
        "law": _guardian("law"),
        "technology": _guardian("technology"),
        "science": _guardian("science"),
        "health": _guardian("society/health"),
        "environment": _guardian("environment"),
        "sports": _guardian("sport"),
        "culture": _guardian("culture"),
        "education": _guardian("education"),
        "society": _guardian("society"),
    }),
    Outlet("npr", "NPR", "US", "global", ("feeds.npr.org",), ("npr.org",), {
        "economics": _npr(1017),
        "finance": _npr(1006),
        "business": _npr(1006),
        "policy": _npr(1014),
        "politics": _npr(1014, 1004),
        "technology": _npr(1019),
        "science": _npr(1007),
        "health": _npr(1128),
        "environment": _npr(1025),
        "sports": _npr(1055),
        "culture": _npr(1008),
        "education": _npr(1013),
    }),
    Outlet("hindu", "The Hindu", "IN", "IN", ("thehindu.com",), ("thehindu.com",), {
        "economics": _hindu("business/Economy"),
        "finance": _hindu("business/markets"),
        "business": _hindu("business"),
        "policy": _hindu("news/national"),
        "politics": _hindu("news/national", "news/international"),
        "law": _hindu("news/national"),
        "technology": _hindu("sci-tech/technology"),
        "science": _hindu("sci-tech/science"),
        "health": _hindu("sci-tech/health"),
        "environment": _hindu("sci-tech/energy-and-environment"),
        "sports": _hindu("sport"),
        "culture": _hindu("entertainment"),
        "education": _hindu("education"),
        "society": _hindu("society"),
    }),
    Outlet("express", "The Indian Express", "IN", "IN", ("indianexpress.com",),
           ("indianexpress.com",), {
        "economics": _express("business/economy"),
        "business": _express("business"),
        "politics": _express("india"),
        "technology": _express("technology"),
        "health": _express("lifestyle/health"),
        "sports": _express("sports"),
        "culture": _express("entertainment"),
        "education": _express("education"),
    }),
    Outlet("mint", "Mint", "IN", "IN", ("livemint.com",), ("livemint.com",), {
        "economics": _mint("economy"),
        "finance": _mint("markets", "money"),
        "business": _mint("companies"),
        "politics": _mint("politics"),
        "technology": _mint("technology"),
    }),
    Outlet("et", "The Economic Times", "IN", "IN", ("economictimes.indiatimes.com",),
           ("economictimes.indiatimes.com",), {
        "economics": _et("news/economy/rssfeeds/1373380680.cms"),
        "finance": _et("markets/rssfeeds/1977021501.cms"),
        "policy": _et("news/economy/policy/rssfeeds/1106944246.cms"),
        "politics": _et("news/politics-and-nation/rssfeeds/1052732854.cms"),
        "technology": _et("tech/rssfeeds/13357270.cms"),
    }),
)  # fmt: skip
BY_OUTLET: dict[str, Outlet] = {o.id: o for o in REGISTRY}


def _host_match(host: str, hosts: Sequence[str]) -> bool:
    return any(host == h or host.endswith(f".{h}") for h in hosts)


def outlet_for_host(host: str) -> Outlet | None:
    host = host.lower().removeprefix("www.")
    return next((o for o in REGISTRY if _host_match(host, o.article_hosts)), None)


def eligible(outlet: Outlet, country: str | None) -> Side | None:
    """ "local" for the reader's own country's outlets, "global" for other global outlets, None
    for an outlet this reader isn't offered (another country's national press)."""
    if country is not None and outlet.home == country:
        return "local"
    return "global" if outlet.region == "global" else None


def side_of(host: str, country: str | None) -> Side | None:
    """A result's side by its host: registry outlets per `eligible`, the wires global, any other
    host None (not offered)."""
    outlet = outlet_for_host(host)
    if outlet is not None:
        return eligible(outlet, country)
    return "global" if _host_match(host.lower().removeprefix("www."), WIRE_HOSTS) else None


def fallback_domains() -> list[str]:
    """The search fallback's include_domains: every registry article host plus the wires. One
    constant list for everyone (never filtered by country), so requests can't tell readers
    apart; results a reader isn't offered are dropped after the search."""
    return sorted({h for o in REGISTRY for h in o.article_hosts} | set(WIRE_HOSTS))


def feed_urls() -> list[str]:
    """Every distinct section feed, in registry order (one fetch per URL per run)."""
    return list(dict.fromkeys(u for o in REGISTRY for urls in o.sections.values() for u in urls))
