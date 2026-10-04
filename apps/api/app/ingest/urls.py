"""Canonical URL form and the content id derived from it (Firestore `contents/{url_hash}`)."""

import hashlib
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_DEFAULT_PORTS = {"http": 80, "https": 443}
_TRACKING_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref_src"}


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").rstrip(".")
    if ":" in host:
        host = f"[{host}]"
    netloc = host if parts.port in (None, _DEFAULT_PORTS.get(scheme)) else f"{host}:{parts.port}"
    query = sorted(
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in _TRACKING_PARAMS
    )
    return urlunsplit((scheme, netloc, parts.path or "/", urlencode(query), ""))


def url_hash(url: str) -> str:
    return hashlib.sha256(normalize_url(url).encode()).hexdigest()[:32]
