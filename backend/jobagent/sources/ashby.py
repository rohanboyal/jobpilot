from __future__ import annotations

from ..models import Company
from ..utils.http import get_json, make_client
from ..utils.text import detect_remote, html_to_text, parse_date
from .base import ATSSource, RawJob, SourceContext, register


@register
class Ashby(ATSSource):
    name = "ashby"
    label = "Ashby boards"
    ats_type = "ashby"
    description = "Public posting API (api.ashbyhq.com) of tracked companies."

    def fetch_company(self, ctx: SourceContext, company: Company) -> list[RawJob]:
        url = f"https://api.ashbyhq.com/posting-api/job-board/{company.ats_slug}"
        with make_client(timeout=ctx.settings.source_timeout_s) as client:
            data = get_json(client, url, params={"includeCompensation": "true"})
        out: list[RawJob] = []
        for j in data.get("jobs", []):
            if j.get("isListed") is False:
                continue
            locs = [j.get("location")] + [s.get("location") for s in j.get("secondaryLocations") or []]
            location = ", ".join(x for x in locs if x) or None
            desc = j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml"))
            comp = (j.get("compensation") or {}).get("compensationTierSummary")
            out.append(RawJob(
                source=self.name,
                external_id=str(j.get("id")),
                title=j.get("title") or "",
                company_name=company.name,
                url=j.get("jobUrl") or url,
                apply_url=j.get("applyUrl") or j.get("jobUrl"),
                location=location,
                remote=bool(j.get("isRemote")) if j.get("isRemote") is not None else detect_remote(j.get("title"), location, desc),
                employment_type=j.get("employmentType"),
                description=desc,
                posted_at=parse_date(j.get("publishedAt")),
                salary_text=comp,
                raw={"department": j.get("department"), "team": j.get("team")},
            ))
        return out
