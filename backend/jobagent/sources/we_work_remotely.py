"""We Work Remotely through its public all-jobs RSS feed (full postings, region, type and expiry per item)."""

from __future__ import annotations

import re
from collections.abc import Iterable

from ..utils.feeds import parse_feed
from ..utils.http import get, make_client
from ..utils.text import html_to_text, parse_date
from .base import RawJob, Source, SourceContext, fetched_within, register, skill_hit, title_passes

FEED = "https://weworkremotely.com/remote-jobs.rss"
_TECH_CATEGORIES = ("programming", "devops", "sysadmin", "data")
_WEBSITE = re.compile(r"URL:</strong>\s*<a href=\"([^\"]+)\"", re.I)


def split_company_title(packed: str) -> tuple[str, str]:
    """'DuckDuckGo: Senior Backend Engineer' -> ('DuckDuckGo', 'Senior Backend Engineer')."""
    company, sep, title = packed.partition(": ")
    return (company.strip(), title.strip()) if sep else ("", packed.strip())


@register
class WeWorkRemotely(Source):
    name = "we_work_remotely"
    label = "We Work Remotely"
    kind = "board"
    priority = 2
    description = ("Public RSS feed of weworkremotely.com (about 90 newest postings across categories, full text and "
                   "region), kept when the title matches your keywords or a programming post mentions your skills. "
                   "Fetched at most every 6 hours.")

    def fetch(self, ctx: SourceContext) -> Iterable[RawJob]:
        if not ctx.search.remote_ok:
            ctx.log("We Work Remotely skipped: remote_ok is false")
            return
        if fetched_within(ctx, self.name, 6):
            ctx.log("We Work Remotely skipped: fetched less than 6 hours ago")
            return
        with make_client(timeout=ctx.settings.source_timeout_s) as client:
            r = get(client, FEED)
        for item in parse_feed(r.text):
            company, title = split_company_title(item.title)
            category = (item.extra.get("category") or "").lower()
            text = html_to_text(item.summary)
            technical = any(c in category for c in _TECH_CATEGORIES)
            if not item.link or (not title_passes(ctx, title) and not (technical and skill_hit(ctx, text[:4000]))):
                continue
            m = _WEBSITE.search(item.summary or "")
            region = item.extra.get("region") or "Remote"
            yield RawJob(
                source=self.name, external_id=item.link.rstrip("/").split("/")[-1], title=title, company_name=company,
                url=item.link, apply_url=item.link, location=region, remote=True,
                employment_type=item.extra.get("type") or None, description=text or None,
                posted_at=parse_date(item.published), company_website=m.group(1) if m else None,
                raw={"category": item.extra.get("category"), "expires_at": item.extra.get("expires_at")},
            )
