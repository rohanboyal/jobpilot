"""ZipRecruiter India through the board's public RSS syndication feed.

The HTML search page sits behind a bot check and ziprecruiter.com (US) forbids automated access outright, so only
the .in feed is read: the newest ~50 postings per query, filtered locally by title keywords.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from urllib.parse import quote_plus

from ..utils.feeds import parse_feed
from ..utils.http import get, make_client, polite_sleep
from ..utils.text import detect_remote, html_to_text, normalize_ws, parse_date
from .base import RawJob, Source, SourceContext, register, title_passes

FEED = "https://www.ziprecruiter.in/jobs.rss"
# "<title>  at <company> (<locations>)": a title may itself contain parentheses; the location group is the last one
_PACKED = re.compile(r"^(?P<title>.+?)\s+at\s+(?P<company>.+?)\s*\((?P<loc>[^()]*)\)\s*$")
_ID = re.compile(r"/jobs/(\d+)")


def split_packed_title(packed: str) -> tuple[str, str, str]:
    """'Java Developer (GCP)  at ACME LTD (Chennai, TN,Pune, MH, IN)' -> (title, company, locations)."""
    text = normalize_ws(packed.replace("\xa0", " "))
    m = _PACKED.match(text)
    if not m:
        return text, "", ""
    return m["title"].strip(), m["company"].strip(), re.sub(r"\s*,\s*", ", ", m["loc"]).strip()


@register
class ZipRecruiterIndia(Source):
    name = "ziprecruiter_in"
    label = "ZipRecruiter India (RSS)"
    kind = "board"
    priority = 2
    fragile = True
    description = ("Public RSS feed of ziprecruiter.in: the newest ~50 postings per query, India only, filtered by your "
                   "title keywords. Descriptions are short snippets; the full posting opens on the job page.")

    def fetch(self, ctx: SourceContext) -> Iterable[RawJob]:
        if "in" not in {c.lower() for c in ctx.search.countries}:
            ctx.log("ZipRecruiter India skipped: 'in' is not in your countries")
            return
        urls = [FEED] + [f"{FEED}?q={quote_plus(t)}" for t in self.search_terms(ctx, 3)]
        seen: set[str] = set()
        with make_client(timeout=ctx.settings.source_timeout_s) as client:
            for url in urls:
                try:
                    r = get(client, url)
                except Exception as e:
                    ctx.log(f"ZipRecruiter feed {url}: {e}")
                    continue
                for item in parse_feed(r.text):
                    m = _ID.search(item.link or "")
                    ext = m.group(1) if m else item.link
                    if not ext or ext in seen:
                        continue
                    seen.add(ext)
                    title, company, location = split_packed_title(item.title)
                    if not title_passes(ctx, title):
                        continue
                    snippet = html_to_text(item.summary)
                    yield RawJob(
                        source=self.name, external_id=ext, title=title, company_name=company, url=item.link,
                        apply_url=item.link, location=location or None, remote=detect_remote(title, location, snippet),
                        description=snippet or None, posted_at=parse_date(item.published),
                    )
                polite_sleep(0.5, 0.5)
