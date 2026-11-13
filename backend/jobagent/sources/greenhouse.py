from __future__ import annotations

import html as htmllib

from ..models import Company
from ..utils.http import get_json, make_client
from ..utils.text import detect_remote, html_to_text, parse_date
from .base import ATSSource, RawJob, SourceContext, register


@register
class Greenhouse(ATSSource):
    name = "greenhouse"
    label = "Greenhouse boards"
    ats_type = "greenhouse"
    description = "Public JSON job boards (boards-api.greenhouse.io) of tracked companies."

    def fetch_company(self, ctx: SourceContext, company: Company) -> list[RawJob]:
        url = f"https://boards-api.greenhouse.io/v1/boards/{company.ats_slug}/jobs"
        with make_client(timeout=ctx.settings.source_timeout_s) as client:
            data = get_json(client, url, params={"content": "true"})
        out: list[RawJob] = []
        for j in data.get("jobs", []):
            content = htmllib.unescape(j.get("content") or "")
            loc = (j.get("location") or {}).get("name")
            offices = ", ".join(o.get("name", "") for o in j.get("offices", []) if o.get("name"))
            location = loc or offices or None
            desc = html_to_text(content)
            out.append(RawJob(
                source=self.name,
                external_id=str(j.get("id")),
                title=j.get("title") or "",
                company_name=company.name,
                url=j.get("absolute_url") or url,
                # the embedded board always renders the form itself, even for companies hosting the board on their own site
                apply_url=f"https://job-boards.greenhouse.io/embed/job_app?for={company.ats_slug}&token={j.get('id')}",
                location=location,
                remote=detect_remote(j.get("title"), location, desc),
                description=desc,
                posted_at=parse_date(j.get("first_published") or j.get("updated_at")),
                raw={"departments": [d.get("name") for d in j.get("departments", [])],
                     "updated_at": j.get("updated_at")},
            ))
        return out
