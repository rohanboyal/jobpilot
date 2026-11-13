"""Jobicy remote jobs through its documented public API (keyless; asks for at most one sync pass per hour)."""

from __future__ import annotations

from collections.abc import Iterable

from ..utils.http import get_json, make_client, polite_sleep
from ..utils.text import html_to_text, parse_date
from .base import RawJob, Source, SourceContext, fetched_within, register, title_passes

API = "https://jobicy.com/api/v2/remote-jobs"
GEOS = ("anywhere", "apac")     # the API has no India slug; worldwide and APAC roles are the ones open to India
PAGES = 2


@register
class Jobicy(Source):
    name = "jobicy"
    label = "Jobicy (remote jobs)"
    kind = "board"
    priority = 2
    description = ("Documented public API of jobicy.com: engineering postings from the last 7 days that are open "
                   "worldwide or in APAC, filtered by your title keywords. Fetched at most every 6 hours.")

    def fetch(self, ctx: SourceContext) -> Iterable[RawJob]:
        if not ctx.search.remote_ok:
            ctx.log("Jobicy skipped: remote_ok is false")
            return
        if fetched_within(ctx, self.name, 6):
            ctx.log("Jobicy skipped: fetched less than 6 hours ago")
            return
        seen: set[str] = set()
        with make_client(timeout=ctx.settings.source_timeout_s) as client:
            for geo in GEOS:
                cursor = None
                for _ in range(PAGES):
                    params: dict[str, str | int] = {"count": 200, "industry": "engineering", "geo": geo}
                    if cursor:
                        params["cursor"] = cursor
                    try:
                        data = get_json(client, API, params=params)
                    except Exception as e:
                        ctx.log(f"Jobicy {geo}: {e}")
                        break
                    for j in data.get("jobs") or []:
                        jid = str(j.get("id") or "")
                        title = j.get("jobTitle") or ""
                        if not jid or jid in seen or not title_passes(ctx, title):
                            continue
                        seen.add(jid)
                        salary = None
                        if j.get("salaryMin") or j.get("salaryMax"):
                            salary = (f"{j.get('salaryCurrency') or ''} {j.get('salaryMin') or ''}-"
                                      f"{j.get('salaryMax') or ''} {j.get('salaryPeriod') or ''}").strip()
                        yield RawJob(
                            source=self.name, external_id=jid, title=title, company_name=j.get("companyName") or "",
                            url=j.get("url") or "", apply_url=j.get("url"),
                            location=f"Remote ({j.get('jobGeo') or geo})", remote=True,
                            employment_type=", ".join(j.get("jobType") or []) or None, salary_text=salary,
                            description=html_to_text(j.get("jobDescription")) or j.get("jobExcerpt"),
                            posted_at=parse_date(j.get("pubDate")),
                            raw={"level": j.get("jobLevel"), "industry": j.get("jobIndustry")},
                        )
                    cursor = data.get("nextCursor")
                    if not data.get("hasMore") or not cursor:
                        break
                    polite_sleep(0.5, 0.5)
