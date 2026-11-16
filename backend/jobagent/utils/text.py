"""Text helpers: HTML to text, normalization, dates, remote detection."""

from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime, timedelta

from bs4 import BeautifulSoup
from dateutil import parser as dateparser

_BLOCK_TAGS = {"p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "article"}


def html_to_text(html: str | None) -> str:
    if not html:
        return ""
    if "<" not in html:
        return normalize_ws(html)
    soup = BeautifulSoup(html, "lxml")
    for t in soup(["script", "style", "noscript", "svg"]):
        t.decompose()
    for tag in soup.find_all(_BLOCK_TAGS):
        tag.insert_before("\n")
        tag.insert_after("\n")
    text = soup.get_text(" ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def normalize_ws(s: str | None) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


_MOJIBAKE = re.compile(r"[\u00c2\u00c3\u00e2][\u0080-\u00bf]")


def fix_mojibake(s: str | None) -> str:
    """Repair UTF-8 text that a feed double-encoded as Latin-1 ("Sothebyâ\x80\x99s" -> "Sotheby's")."""
    if not s or not _MOJIBAKE.search(s):
        return s or ""
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


_PAREN_NOISE = re.compile(
    r"\((?:\s*(?:remote|hybrid|on-?site|in-?office|contract|contractor|freelance|full-?time|part-?time|temporary|"
    r"m/w/d|w/m/d|f/m/d|d/f/m|m/f/d|all genders|x/f/m)\s*)\)"
)


def norm_key(s: str | None) -> str:
    """Lowercase, ascii-fold, strip punctuation. Used for fingerprints."""
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    s = s.lower()
    s = _PAREN_NOISE.sub(" ", s)             # drop (Remote) / (Contract) but keep (Backend) vs (Frontend)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return normalize_ws(s)


def slugify(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", (s or "").lower())).strip("-")


def truncate(s: str | None, n: int) -> str:
    s = s or ""
    return s if len(s) <= n else s[: n - 1] + "…"


_REL = re.compile(r"(\d+)\s*(minute|min|hour|hr|day|week|month)s?\s+ago", re.I)


def parse_date(value) -> datetime | None:
    """Accepts ISO strings, epoch seconds/milliseconds, and '3 days ago'. Returns naive UTC."""
    if value is None or value == "":
        return None
    now = datetime.now(UTC)
    try:
        if isinstance(value, int | float):
            v = float(value)
            if v > 1e12:
                v /= 1000.0
            return datetime.fromtimestamp(v, UTC).replace(tzinfo=None)
        s = str(value).strip()
        if s.isdigit():
            return parse_date(int(s))
        m = _REL.search(s)
        if m:
            n, unit = int(m.group(1)), m.group(2).lower()
            delta = {
                "minute": timedelta(minutes=n), "min": timedelta(minutes=n),
                "hour": timedelta(hours=n), "hr": timedelta(hours=n),
                "day": timedelta(days=n), "week": timedelta(weeks=n), "month": timedelta(days=30 * n),
            }[unit]
            return (now - delta).replace(tzinfo=None)
        if s.lower() in {"today", "just now", "just posted"}:
            return now.replace(tzinfo=None)
        if s.lower() == "yesterday":
            return (now - timedelta(days=1)).replace(tzinfo=None)
        dt = dateparser.parse(s)
        if dt is None:
            return None
        if dt.tzinfo is not None:
            dt = dt.astimezone(UTC).replace(tzinfo=None)
        return dt
    except (ValueError, OverflowError, TypeError):
        return None


_REMOTE_RE = re.compile(r"\b(remote|work from home|wfh|anywhere|distributed)\b", re.I)
_ONSITE_RE = re.compile(r"\b(on-?site|in-?office|hybrid)\b", re.I)


def detect_remote(title: str | None, location: str | None, description: str | None = None) -> bool | None:
    head = f"{title or ''} {location or ''}"
    if _REMOTE_RE.search(head):
        return True
    if _ONSITE_RE.search(head):
        return False
    if description:
        first = description[:600]
        if _REMOTE_RE.search(first) and not _ONSITE_RE.search(first):
            return True
    return None


def domain_of(url: str | None) -> str | None:
    if not url:
        return None
    import tldextract

    ext = tldextract.extract(url)
    if not ext.domain:
        return None
    return ".".join(p for p in (ext.domain, ext.suffix) if p)


def title_has(title: str, keyword: str) -> bool:
    """`keyword` at the start of a word in `title`: "llm" matches "LLM Engineer", "engineer" matches "Engineering",
    but "ai" doesn't match "Maintenance" or "Chairman". Short keywords (3 letters or fewer) must be whole words."""
    k = re.escape(" ".join(keyword.lower().split()))
    end = r"(?![a-z0-9])" if len(keyword.strip()) <= 3 else ""
    return re.search(rf"(?<![a-z0-9]){k}{end}", title) is not None
