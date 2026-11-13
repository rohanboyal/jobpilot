"""Arbeitnow (Germany/EU board) through its free public API. Off by default: enable it when you target the EU."""

from __future__ import annotations

import html
from collections.abc import Iterable

from ..utils.http import get_json, make_client, polite_sleep
from ..utils.text import html_to_text, parse_date
from .base import RawJob, Source, SourceContext, register, title_passes

API = "https://www.arbeitnow.com/api/job-board-api"
PAGES = 2        # 300 newest jobs per page, roughly a day of postings each


@register
class Arbeitnow(Source):
    name = "arbeitnow"
    label = "Arbeitnow (Germany / EU)"
    kind = "board"
    priority = 2
    default_enabled = False
    description = ("Free public API of arbeitnow.com: Berlin/Munich/Zurich/Amsterdam/Paris/London postings, a few EU-remote. "
                   "Filtered by your title keywords. Enable it if you target the EU.")

    def fetch(self, ctx: SourceContext) -> Iterable[RawJob]:
        with make_client(timeout=ctx.settings.source_timeout_s) as client:
            for page in range(1, PAGES + 1):
                try:
                    data = get_json(client, API, params={"page": page})
                except Exception as e:
                    ctx.log(f"Arbeitnow p{page}: {e}")
                    break
                for j in data.get("data") or []:
                    title = html.unescape(j.get("title") or "")
                    if not title_passes(ctx, title):
                        continue
                    yield RawJob(
                        source=self.name, external_id=j.get("slug"), title=title,
                        company_name=html.unescape(j.get("company_name") or ""), url=j.get("url") or "",
                        apply_url=j.get("url"), location=j.get("location") or None, remote=bool(j.get("remote")),
                        employment_type=", ".join(j.get("job_types") or [])[:60] or None,
                        description=html_to_text(j.get("description")), posted_at=parse_date(j.get("created_at")),
                        raw={"tags": (j.get("tags") or [])[:10]},
                    )
                if not (data.get("links") or {}).get("next"):
                    break
                polite_sleep(0.6, 0.6)
