"""Jurisdiction cues and the candidate filter for entity linking (M2.2, issue #6). Pure.

A UK "Chancellor" must not link to the US Treasury Secretary. Roles, institutions, regulators,
committees, policies, taxes and schemes belong to one country (`Concept.jurisdiction`); the
article tells us where it is from through its site, its web address, its currency symbols and the
countries it names. A candidate of one of those kinds is dropped when it belongs to a country the
article gives no sign of. With no cues at all nothing is dropped (we don't know enough), and
`global` concepts always stay. link_confirm v3 also sees each candidate's kind and jurisdiction.
"""

import re
from collections.abc import Iterable
from urllib.parse import urlsplit

JURISDICTIONAL_KINDS = frozenset(
    {"role", "institution", "regulator", "committee", "policy", "tax", "scheme"}
)
EU_MEMBERS = frozenset(
    {"AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE", "IT",
     "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE"}
)  # fmt: skip

SITE_COUNTRY = {
    "BBC News": "GB",
    "The Guardian": "GB",
    "Mint": "IN",
    "The Economic Times": "IN",
    "BusinessLine": "IN",
    "Business Standard": "IN",
    "The Hindu": "IN",
}
TLD_COUNTRY = {
    ".uk": "GB", ".in": "IN", ".au": "AU", ".ca": "CA", ".de": "DE", ".fr": "FR", ".ie": "IE",
    ".nz": "NZ", ".sg": "SG", ".za": "ZA", ".jp": "JP", ".cn": "CN", ".pk": "PK", ".eu": "EU",
}  # fmt: skip
CURRENCY_COUNTRY = {"₹": "IN", "£": "GB", "€": "EU", "US$": "US", "A$": "AU", "C$": "CA"}
# Country names and demonyms → ISO code. Whole-word, case-sensitive (so "US" is not "us").
_NAMES = {
    "GB": "UK|U\\.K\\.|Britain|British|England|English|Scotland|Scottish|Wales|Welsh|London"
          "|Westminster|Downing Street",
    "IN": "India|Indian|New Delhi|Delhi|Mumbai",
    "US": "US|U\\.S\\.|USA|United States|American|Washington|Wall Street|Congress",
    "DE": "Germany|German|Berlin",
    "FR": "France|French|Paris",
    "CN": "China|Chinese|Beijing",
    "JP": "Japan|Japanese|Tokyo",
    "AU": "Australia|Australian|Canberra",
    "CA": "Canada|Canadian|Ottawa",
    "EU": "EU|European Union|Brussels|eurozone",
}  # fmt: skip
_NAME_RE = {code: re.compile(rf"(?<![\w.])(?:{alts})(?![\w])") for code, alts in _NAMES.items()}


def cues(site: str = "", url: str = "", text: str = "") -> frozenset[str]:
    """Countries (ISO alpha-2, or EU) the article gives signs of."""
    found: set[str] = set()
    if site in SITE_COUNTRY:
        found.add(SITE_COUNTRY[site])
    host = urlsplit(url).hostname or ""
    for tld, code in TLD_COUNTRY.items():
        if host.endswith(tld):
            found.add(code)
    for symbol, code in CURRENCY_COUNTRY.items():
        if symbol in text:
            found.add(code)
    for code, pattern in _NAME_RE.items():
        if pattern.search(text):
            found.add(code)
    return frozenset(found)


def allowed(kind: str | None, jurisdiction: str, article: Iterable[str]) -> bool:
    """Keep the candidate unless it is a jurisdictional kind from a country with no cue."""
    article = frozenset(article)
    if not article or jurisdiction == "global" or kind not in JURISDICTIONAL_KINDS:
        return True
    if jurisdiction in article:
        return True
    if jurisdiction == "EU":  # an EU body applies in every member state
        return bool(article & EU_MEMBERS)
    return False
