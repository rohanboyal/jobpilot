"""Fingerprints: exact identity per source, and a softer key to spot the same role across sources."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .text import norm_key

_TRACKING = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "gh_src", "lever-source",
             "ref", "source", "src", "trk", "trackingid", "refid", "position", "pagenum", "currentjobid"}

_LOCATION_NOISE = re.compile(r"\b(india|usa|united states|us|uk|united kingdom|remote|hybrid|onsite|on site)\b")


def canonical_url(url: str) -> str:
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url
    q = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=False) if k.lower() not in _TRACKING]
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme.lower() or "https", parts.netloc.lower(), path, urlencode(q), ""))


def _sha(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def fingerprint(*, source: str, external_id: str | None, url: str, company: str, title: str, location: str | None) -> str:
    if external_id:
        return _sha(f"{source}|id|{external_id}")
    cu = canonical_url(url)
    if cu:
        return _sha(f"{source}|url|{cu}")
    return _sha(f"{source}|txt|{norm_key(company)}|{norm_key(title)}|{norm_key(location)}")


def dedup_key(company: str, title: str, location: str | None) -> str:
    """Same company + title + rough location → same key, regardless of which site we saw it on."""
    loc = _LOCATION_NOISE.sub(" ", norm_key(location)).split()
    loc = loc[0] if loc else ""          # the city is almost always first; state/country spellings vary too much
    return _sha(f"{norm_key(company)}|{norm_key(title)}|{loc}")
