"""Working Nomads through the public JSON endpoint linked from the site footer (the recent 'exposed' subset)."""

from __future__ import annotations

import re
from collections.abc import Iterable

from ..utils.http import get_json, make_client
from ..utils.text import html_to_text, parse_date
from .base import RawJob, Source, SourceContext, fetched_within, register, skill_hit, title_passes

API = "https://www.workingnomads.com/api/exposed_jobs/"
_ID = re.compile(r"/job/go/(\d+)")


@register
class WorkingNomads(Source):
    name = "working_nomads"
    label = "Working Nomads (remote jobs)"
    kind = "board"
    priority = 2
    description = ("Public JSON of workingnomads.com (roughly the last month of remote postings), kept when the title "
                   "matches your keywords or the tags match your skills. Fetched at most every 6 hours.")

    def fetch(self, ctx: SourceContext) -> Iterable[RawJob]:
        if not ctx.search.remote_ok:
            ctx.log("Working Nomads skipped: remote_ok is false")
            return
        if fetched_within(ctx, self.name, 6):
            ctx.log("Working Nomads skipped: fetched less than 6 hours ago")
            return
        with make_client(timeout=ctx.settings.source_timeout_s) as client:
            data = get_json(client, API)
        if not isinstance(data, list):
            ctx.log("Working Nomads: unexpected payload")
            return
        for j in data:
            title = j.get("title") or ""
            tags = [t.strip().lower() for t in (j.get("tags") or "").split(",") if t.strip()]
            if not title_passes(ctx, title) and not skill_hit(ctx, " ".join(tags)):
                continue
            url = j.get("url") or ""
            m = _ID.search(url)
            yield RawJob(
                source=self.name, external_id=m.group(1) if m else url, title=title,
                company_name=j.get("company_name") or "", url=url, apply_url=url,
                location=j.get("location") or "Remote", remote=True,
                description=html_to_text(j.get("description")), posted_at=parse_date(j.get("pub_date")),
                raw={"category": j.get("category_name"), "tags": tags[:12]},
            )
