"""Himalayas remote jobs through its documented public JSON API (keyless; the data refreshes daily)."""

from __future__ import annotations

from collections.abc import Iterable

from ..utils.http import get_json, make_client, polite_sleep
from ..utils.text import html_to_text, parse_date
from .base import RawJob, Source, SourceContext, fetched_within, register, title_passes

SEARCH = "https://himalayas.app/jobs/api/search"
PAGES = 3          # 20 jobs per page, newest first


@register
class Himalayas(Source):
    name = "himalayas"
    label = "Himalayas (remote jobs)"
    kind = "board"
    priority = 2
    description = ("Documented public API of himalayas.app: remote roles open to your country or worldwide, one query per "
                   "role, newest first. The data refreshes daily, so it is fetched at most once every 20 hours.")

    def fetch(self, ctx: SourceContext) -> Iterable[RawJob]:
        if not ctx.search.remote_ok:
            ctx.log("Himalayas skipped: remote_ok is false")
            return
        if fetched_within(ctx, self.name, 20):
            ctx.log("Himalayas skipped: fetched less than 20 hours ago (the API refreshes daily)")
            return
        countries = [c.upper() for c in ctx.search.countries if c.strip()][:2] or [None]
        seen: set[str] = set()
        with make_client(timeout=ctx.settings.source_timeout_s) as client:
            for term in self.search_terms(ctx, 3):
                for country in countries:
                    for page in range(1, PAGES + 1):
                        params: dict[str, str | int] = {"q": term, "sort": "recent", "page": page}
                        if country:
                            params["country"] = country
                        try:
                            data = get_json(client, SEARCH, params=params)
                        except Exception as e:
                            ctx.log(f"Himalayas {term}/{country or 'any'} p{page}: {e}")
                            break
                        jobs = data.get("jobs") or []
                        for j in jobs:
                            guid = j.get("guid") or ""
                            title = j.get("title") or ""
                            if not guid or guid in seen or not title_passes(ctx, title):
                                continue
                            seen.add(guid)
                            restrictions = j.get("locationRestrictions") or []
                            salary = None
                            if j.get("minSalary") or j.get("maxSalary"):
                                salary = (f"{j.get('currency') or ''} {j.get('minSalary') or ''}-{j.get('maxSalary') or ''} "
                                          f"{j.get('salaryPeriod') or ''}").strip()
                            yield RawJob(
                                source=self.name, external_id=guid, title=title, company_name=j.get("companyName") or "",
                                url=guid, apply_url=j.get("applicationLink") or guid,
                                location=("Remote: " + ", ".join(restrictions)) if restrictions else "Remote (worldwide)",
                                remote=True, employment_type=j.get("employmentType"), salary_text=salary,
                                description=html_to_text(j.get("description")) or j.get("excerpt"),
                                posted_at=parse_date(j.get("pubDate")),
                                raw={"seniority": j.get("seniority"), "categories": (j.get("categories") or [])[:8],
                                     "expires": j.get("expiryDate")},
                            )
                        if len(jobs) < 20:
                            break
                        polite_sleep(0.4, 0.4)
