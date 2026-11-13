"""Jobspresso (curated remote jobs) through its public WP Job Manager feed (the 10 newest postings)."""

from __future__ import annotations

from collections.abc import Iterable

from ..utils.feeds import parse_feed
from ..utils.http import get, make_client
from ..utils.text import html_to_text, parse_date
from .base import RawJob, Source, SourceContext, fetched_within, register, title_passes

FEED = "https://jobspresso.co/feed/job_feed/"


@register
class Jobspresso(Source):
    name = "jobspresso"
    label = "Jobspresso (curated remote jobs)"
    kind = "board"
    priority = 2
    description = ("Public job feed of jobspresso.co (the 10 newest curated remote postings per fetch, with company, "
                   "region, salary and the full text), filtered by your title keywords. Fetched at most every 6 hours.")

    def fetch(self, ctx: SourceContext) -> Iterable[RawJob]:
        if not ctx.search.remote_ok:
            ctx.log("Jobspresso skipped: remote_ok is false")
            return
        if fetched_within(ctx, self.name, 6):
            ctx.log("Jobspresso skipped: fetched less than 6 hours ago")
            return
        with make_client(timeout=ctx.settings.source_timeout_s) as client:
            r = get(client, FEED)
        for item in parse_feed(r.text):
            if not item.link or not title_passes(ctx, item.title):
                continue
            x = item.extra
            region = x.get("job_listing:location") or ""
            company = x.get("job_listing:company") or (x.get("dc:creator") or "").split("<br")[0].strip()
            yield RawJob(
                source=self.name, external_id=x.get("post-id") or item.guid or item.link, title=item.title,
                company_name=company, url=item.link, apply_url=item.link,
                location=f"Remote ({region})" if region else "Remote", remote=True,
                employment_type=x.get("job_listing:job_type") or None, salary_text=x.get("job_listing:salary") or None,
                description=html_to_text(item.content or item.summary), posted_at=parse_date(item.published),
                raw={"category": x.get("job_listing:job_category")},
            )
