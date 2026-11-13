from __future__ import annotations

from ..models import Company
from ..utils.http import get_json, make_client
from ..utils.text import detect_remote, html_to_text, parse_date
from .base import ATSSource, RawJob, SourceContext, register


@register
class Workable(ATSSource):
    name = "workable"
    label = "Workable boards"
    ats_type = "workable"
    description = "Public widget API (apply.workable.com) of tracked companies."

    def fetch_company(self, ctx: SourceContext, company: Company) -> list[RawJob]:
        url = f"https://apply.workable.com/api/v1/widget/accounts/{company.ats_slug}"
        with make_client(timeout=ctx.settings.source_timeout_s) as client:
            data = get_json(client, url, params={"details": "true"})
        out: list[RawJob] = []
        for j in data.get("jobs", []):
            location = ", ".join(x for x in (j.get("city"), j.get("state"), j.get("country")) if x) or None
            desc = "\n\n".join(html_to_text(j.get(k)) for k in ("description", "requirements", "benefits") if j.get(k))
            job_url = j.get("url") or j.get("shortlink") or url
            out.append(RawJob(
                source=self.name,
                external_id=str(j.get("shortcode") or j.get("code") or job_url),
                title=j.get("title") or "",
                company_name=data.get("name") or company.name,
                url=job_url,
                apply_url=j.get("application_url") or job_url.rstrip("/") + "/apply",
                location=location,
                remote=True if j.get("telecommuting") else detect_remote(j.get("title"), location, desc),
                employment_type=j.get("employment_type"),
                description=desc,
                posted_at=parse_date(j.get("published_on") or j.get("created_at")),
                raw={"department": j.get("department"), "function": j.get("function")},
            ))
        return out
