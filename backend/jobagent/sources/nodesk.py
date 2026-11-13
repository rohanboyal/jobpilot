"""NoDesk (remote jobs) through its static RSS feeds (10 newest items per feed; the site's terms forbid crawling pages)."""

from __future__ import annotations

from collections.abc import Iterable

from ..utils.feeds import parse_feed
from ..utils.http import get, make_client, polite_sleep
from ..utils.text import parse_date
from .base import RawJob, Source, SourceContext, fetched_within, register, skill_hit, title_passes

FEEDS = ("https://nodesk.co/remote-jobs/engineering/index.xml", "https://nodesk.co/remote-jobs/index.xml")


def split_role_company(title: str) -> tuple[str, str]:
    """'Software Engineer, AI Coding Tasks at Askable' -> ('Software Engineer, AI Coding Tasks', 'Askable')."""
    head, sep, tail = title.rpartition(" at ")
    return (head.strip(), tail.strip()) if sep else (title.strip(), "")


@register
class NoDesk(Source):
    name = "nodesk"
    label = "NoDesk (remote jobs)"
    kind = "board"
    priority = 2
    description = ("Public RSS feeds of nodesk.co (engineering + all jobs, 10 newest each), kept when the title matches "
                   "your keywords or the excerpt mentions your skills. Fetched at most every 6 hours.")

    def fetch(self, ctx: SourceContext) -> Iterable[RawJob]:
        if not ctx.search.remote_ok:
            ctx.log("NoDesk skipped: remote_ok is false")
            return
        if fetched_within(ctx, self.name, 6):
            ctx.log("NoDesk skipped: fetched less than 6 hours ago")
            return
        seen: set[str] = set()
        with make_client(timeout=ctx.settings.source_timeout_s) as client:
            for feed in FEEDS:
                try:
                    r = get(client, feed)
                except Exception as e:
                    ctx.log(f"NoDesk {feed}: {e}")
                    continue
                for item in parse_feed(r.text):
                    if not item.link or item.link in seen:
                        continue
                    seen.add(item.link)
                    title, company = split_role_company(item.title)
                    if not title_passes(ctx, title) and not skill_hit(ctx, item.summary):
                        continue
                    yield RawJob(
                        source=self.name, external_id=item.link.rstrip("/").split("/")[-1], title=title,
                        company_name=company, url=item.link, apply_url=item.link, location="Remote", remote=True,
                        description=item.summary or None, posted_at=parse_date(item.published),
                    )
                polite_sleep(0.3, 0.3)
