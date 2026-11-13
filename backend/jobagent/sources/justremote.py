"""JustRemote through the keyless JSON backend its own front end uses (undocumented, so best effort).

The list call returns the whole active board; postings in the developer/devops categories or matching your title
keywords get one detail call each for the full text, posted date and the external apply link.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from ..utils.http import get_json, make_client, polite_sleep
from ..utils.text import html_to_text, parse_date
from .base import RawJob, Source, SourceContext, fetched_within, register, title_passes

API = "https://justremote-api.herokuapp.com/api/v1/jobs"
SITE = "https://justremote.co/"
_TECH_CATEGORIES = {"developer", "devopsandsysadmin"}
_HREF = re.compile(r'href="([^"]+)"')


@register
class JustRemote(Source):
    name = "justremote"
    label = "JustRemote"
    kind = "board"
    priority = 3
    fragile = True
    description = ("Small curated remote board (justremote.co) read through its own JSON backend; most roles are "
                   "US-resident only, a few are open worldwide. Fetched at most every 6 hours.")

    def fetch(self, ctx: SourceContext) -> Iterable[RawJob]:
        if not ctx.search.remote_ok:
            ctx.log("JustRemote skipped: remote_ok is false")
            return
        if fetched_within(ctx, self.name, 6):
            ctx.log("JustRemote skipped: fetched less than 6 hours ago")
            return
        details_left = min(ctx.settings.max_detail_fetches_per_run, 30)
        with make_client(timeout=ctx.settings.source_timeout_s) as client:
            data = get_json(client, API)
            if not isinstance(data, list):
                ctx.log("JustRemote: unexpected payload")
                return
            for j in data:
                title = j.get("title") or ""
                href = (j.get("href") or "").lstrip("/")
                if not href or j.get("is_active") is False:
                    continue
                if not title_passes(ctx, title) and j.get("category") not in _TECH_CATEGORIES:
                    continue
                url = SITE + href
                restrictions = j.get("location_restrictions") or []
                description = apply_url = website = None
                posted = parse_date(j.get("date"))
                if details_left > 0:
                    details_left -= 1
                    try:
                        d = get_json(client, f"{API}/{href.rsplit('/', 1)[-1]}")
                        parts = [d.get("about_company"), d.get("about_role"), d.get("who_looking_for"), d.get("our_offer")]
                        description = html_to_text("\n".join(p for p in parts if p)) or None
                        posted = parse_date(d.get("raw_date")) or posted
                        m = _HREF.search(d.get("apply") or "")
                        apply_url = m.group(1) if m else None
                        site = d.get("company_url")
                        website = (site if site.startswith("http") else f"https://{site}") if site else None
                    except Exception as e:
                        ctx.log(f"JustRemote detail {href}: {e}")
                    polite_sleep(0.3, 0.3)
                yield RawJob(
                    source=self.name, external_id=str(j.get("id") or href), title=title,
                    company_name=j.get("company_name") or "", url=url, apply_url=apply_url or url,
                    location="Remote (" + ", ".join(restrictions) + ")" if restrictions else "Remote (anywhere)",
                    remote=True, employment_type=j.get("job_type"), description=description, posted_at=posted,
                    company_website=website, raw={"category": j.get("category"), "remote_type": j.get("remote_type")},
                )
