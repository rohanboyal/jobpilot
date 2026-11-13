"""Recognize applicant-tracking-system job boards from URLs."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("greenhouse", re.compile(r"^(?:boards|job-boards|boards\.eu|job-boards\.eu)\.greenhouse\.io$")),
    ("lever", re.compile(r"^jobs(?:\.eu)?\.lever\.co$")),
    ("ashby", re.compile(r"^jobs\.ashbyhq\.com$")),
    ("workable", re.compile(r"^apply\.workable\.com$")),
    ("smartrecruiters", re.compile(r"^(?:jobs|careers)\.smartrecruiters\.com$")),
]

_SKIP_SEGMENTS = {"jobs", "job", "embed", "careers", "postings", "o", "j", "application", "apply", ""}


def detect_ats(url: str | None) -> tuple[str, str] | None:
    """Return (ats_type, slug) when `url` points at a known ATS board, else None."""
    if not url:
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    host = parts.netloc.lower().split(":")[0]
    segs = [s for s in parts.path.split("/")]
    for ats, pat in _PATTERNS:
        if pat.match(host):
            first = next((s for s in segs if s), None)
            if ats == "greenhouse" and first == "embed":
                slug = parse_qs(parts.query).get("for", [None])[0]
                return (ats, slug) if slug else None
            if ats == "workable" and first == "j":
                return None   # apply.workable.com/j/<shortcode> carries no account slug
            slug = next((s for s in segs if s and s not in _SKIP_SEGMENTS), None)
            if slug:
                return ats, slug
            return None
    m = re.match(r"^([a-z0-9-]+)\.workable\.com$", host)
    if m and m.group(1) not in {"www", "apply", "jobs"}:
        return "workable", m.group(1)
    m = re.match(r"^([a-z0-9-]+)\.greenhouse\.io$", host)
    if m and m.group(1) not in {"www", "boards", "job-boards", "app", "api"}:
        return "greenhouse", m.group(1)
    return None


def apply_url_for(ats: str | None, job_url: str) -> str:
    """Best-known URL of the application form for a job page on a given ATS."""
    u = job_url.rstrip("/")
    if ats == "lever" and not u.endswith("/apply"):
        return u + "/apply"
    if ats == "ashby" and not u.endswith("/application"):
        return u + "/application"
    if ats == "workable" and "/j/" in u and not u.endswith("/apply"):
        return u + "/apply"
    return job_url
