"""Reed (UK) through its official job-search API. Needs a free personal key: sign in at reed.co.uk, open
https://www.reed.co.uk/developers/jobseeker and register, then set JOBAGENT_REED_API_KEY. Off until then.

Auth is HTTP Basic with the key as the username and an empty password. Full descriptions and the employer's own apply
link come from the details endpoint, fetched only for titles that pass your keywords.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any

from ..utils.http import get_json, make_client, polite_sleep
from ..utils.text import detect_remote, html_to_text
from .base import RawJob, Source, SourceContext, register, title_passes

API = "https://www.reed.co.uk/api/1.0"
DETAILS_PER_RUN = 25


def reed_date(value: Any) -> datetime | None:
    """Reed dates are dd/mm/yyyy."""
    try:
        return datetime.strptime(str(value), "%d/%m/%Y")
    except (TypeError, ValueError):
        return None


def salary(j: dict[str, Any]) -> str | None:
    lo = j.get("yearlyMinimumSalary") or j.get("minimumSalary")
    hi = j.get("yearlyMaximumSalary") or j.get("maximumSalary")
    if not (lo or hi):
        return None
    cur = "£" if (j.get("currency") or "GBP") == "GBP" else f"{j.get('currency')} "
    rng = f"{cur}{int(lo):,} - {cur}{int(hi):,}" if lo and hi and lo != hi else f"{cur}{int(lo or hi):,}"
    return f"{rng} per year" if j.get("yearlyMinimumSalary") or not j.get("salaryType") else f"{rng} {j['salaryType']}"


@register
class Reed(Source):
    name = "reed"
    label = "Reed (UK)"
    kind = "board"
    priority = 2
    default_enabled = False
    description = "Official reed.co.uk job-search API (UK). Needs a free key in JOBAGENT_REED_API_KEY and 'gb' in your countries."

    def fetch(self, ctx: SourceContext) -> Iterable[RawJob]:
        key = ctx.settings.reed_api_key
        if not key:
            ctx.log("Reed skipped: set JOBAGENT_REED_API_KEY (free key from reed.co.uk/developers/jobseeker)")
            return
        if not {"gb", "uk"} & {c.lower() for c in ctx.search.countries}:
            ctx.log("Reed skipped: add 'gb' to your countries to search UK jobs")
            return
        seen: set[str] = set()
        details_left = DETAILS_PER_RUN
        with make_client(timeout=ctx.settings.source_timeout_s, auth=(key, "")) as client:
            for term in self.search_terms(ctx, 3):
                for where in [loc for loc in self.location_terms(ctx, 3) if loc] or [""]:
                    params: dict[str, Any] = {"keywords": term, "resultsToTake": 100, "resultsToSkip": 0}
                    if where:
                        params.update(locationName=where, distanceFromLocation=15)
                    try:
                        data = get_json(client, f"{API}/search", params=params)
                    except Exception as e:
                        ctx.log(f"Reed {term}/{where or 'anywhere'}: {e}")
                        continue
                    for j in data.get("results") or []:
                        jid, title = str(j.get("jobId") or ""), j.get("jobTitle") or ""
                        if not jid or jid in seen or not title_passes(ctx, title):
                            continue
                        seen.add(jid)
                        d: dict[str, Any] = {}
                        if details_left > 0:
                            details_left -= 1
                            try:
                                d = get_json(client, f"{API}/jobs/{jid}")
                            except Exception as e:
                                ctx.log(f"Reed job {jid}: {e}")
                            polite_sleep(0.3, 0.3)
                        merged = {**j, **d}
                        desc = html_to_text(merged.get("jobDescription"))
                        kind = ", ".join(x for x in [merged.get("contractType"),
                                                     "full time" if merged.get("fullTime") else "part time" if merged.get("partTime") else None] if x)
                        url = merged.get("jobUrl") or f"https://www.reed.co.uk/jobs/{jid}"
                        yield RawJob(
                            source=self.name, external_id=jid, title=title, company_name=merged.get("employerName") or "",
                            url=url, apply_url=merged.get("externalUrl") or url, location=merged.get("locationName"),
                            remote=detect_remote(title, merged.get("locationName"), desc), description=desc or None,
                            posted_at=reed_date(merged.get("datePosted") or merged.get("date")),
                            employment_type=kind or None, salary_text=salary(merged),
                            raw={"expires": merged.get("expirationDate"), "applications": merged.get("applications")},
                        )
                    polite_sleep(0.5, 0.5)
