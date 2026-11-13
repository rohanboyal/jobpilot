from __future__ import annotations

from ..models import Company
from ..utils.http import get_json, make_client, polite_sleep
from ..utils.text import html_to_text, parse_date
from .base import ATSSource, RawJob, SourceContext, register, title_passes


@register
class SmartRecruiters(ATSSource):
    name = "smartrecruiters"
    label = "SmartRecruiters boards"
    ats_type = "smartrecruiters"
    description = "Public postings API of tracked companies; descriptions fetched only for title matches."

    def fetch_company(self, ctx: SourceContext, company: Company) -> list[RawJob]:
        base = f"https://api.smartrecruiters.com/v1/companies/{company.ats_slug}/postings"
        out: list[RawJob] = []
        details_left = ctx.settings.max_detail_fetches_per_run
        with make_client(timeout=ctx.settings.source_timeout_s) as client:
            offset = 0
            while offset < ctx.settings.max_jobs_per_source_run:
                data = get_json(client, base, params={"limit": 100, "offset": offset})
                items = data.get("content", [])
                for j in items:
                    loc = j.get("location") or {}
                    location = loc.get("fullLocation") or ", ".join(
                        x for x in (loc.get("city"), loc.get("region"), loc.get("country")) if x) or None
                    title = j.get("name") or ""
                    job_url = f"https://jobs.smartrecruiters.com/{company.ats_slug}/{j.get('id')}"
                    desc = None
                    if details_left > 0 and title_passes(ctx, title):
                        try:
                            det = get_json(client, f"{base}/{j.get('id')}")
                            secs = ((det.get("jobAd") or {}).get("sections") or {})
                            desc = "\n\n".join(
                                f"{s.get('title', '')}\n{html_to_text(s.get('text'))}" for s in secs.values() if s)
                            job_url = det.get("postingUrl") or job_url
                            details_left -= 1
                            polite_sleep(0.3, 0.3)
                        except Exception as e:  # keep the listing even without a description
                            ctx.log(f"    detail failed for {title}: {e}")
                    out.append(RawJob(
                        source=self.name,
                        external_id=str(j.get("id")),
                        title=title,
                        company_name=(j.get("company") or {}).get("name") or company.name,
                        url=job_url,
                        apply_url=job_url,
                        location=location,
                        remote=bool(loc.get("remote")) if loc.get("remote") is not None else None,
                        employment_type=(j.get("typeOfEmployment") or {}).get("label"),
                        description=desc,
                        posted_at=parse_date(j.get("releasedDate")),
                        raw={"department": (j.get("department") or {}).get("label"),
                             "experience": (j.get("experienceLevel") or {}).get("label")},
                    ))
                offset += 100
                if len(items) < 100 or offset >= int(data.get("totalFound") or 0):
                    break
        return out
