"""Arc (arc.dev) remote jobs: the public skill pages are server-rendered and embed their listing JSON (no API/feed)."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any

from ..utils.http import get, make_client, polite_sleep
from ..utils.text import parse_date
from .base import RawJob, Source, SourceContext, register, title_passes

PAGE = "https://arc.dev/remote-jobs/{slug}"
SLUGS = ("python", "software-development", "devops")
_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def parse_next_data(html: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (arcJobs, externalJobs) from a skill page's embedded Next.js payload."""
    m = _NEXT_DATA.search(html or "")
    if not m:
        return [], []
    try:
        props = json.loads(m.group(1)).get("props", {}).get("pageProps", {})
    except (ValueError, AttributeError):
        return [], []
    return props.get("arcJobs") or [], props.get("externalJobs") or []


def _countries(j: dict[str, Any]) -> str:
    req = j.get("requiredCountries") or []
    return "Remote (" + ", ".join(req) + ")" if req else "Remote (anywhere)"


def _categories(j: dict[str, Any]) -> list[str]:
    return [c.get("name") for c in (j.get("categories") or []) if c.get("name")]


@register
class Arc(Source):
    name = "arc"
    label = "Arc (arc.dev remote jobs)"
    kind = "board"
    priority = 3
    fragile = True
    description = ("Public skill pages of arc.dev (python, software development, devops): company postings plus "
                   "Arc-exclusive contracts, with posted date, required countries and experience level. No full "
                   "description until the job page is opened.")

    def fetch(self, ctx: SourceContext) -> Iterable[RawJob]:
        if not ctx.search.remote_ok:
            ctx.log("Arc skipped: remote_ok is false")
            return
        seen: set[str] = set()
        with make_client(timeout=ctx.settings.source_timeout_s) as client:
            for slug in SLUGS:
                try:
                    r = get(client, PAGE.format(slug=slug))
                except Exception as e:
                    ctx.log(f"Arc {slug}: {e}")
                    continue
                arc_jobs, external = parse_next_data(r.text)
                ctx.log(f"Arc {slug}: {len(external)} company postings, {len(arc_jobs)} Arc contracts")
                for j in external:
                    key = j.get("randomKey")
                    title = j.get("title") or ""
                    if not key or key in seen or not title_passes(ctx, title):
                        continue
                    seen.add(key)
                    cats = _categories(j)
                    levels = j.get("experienceLevels") or []
                    yield RawJob(
                        source=self.name, external_id=key, title=title,
                        company_name=(j.get("company") or {}).get("name") or "",
                        url=f"https://arc.dev/remote-jobs/j/{j.get('urlString')}-{key}", location=_countries(j), remote=True,
                        employment_type=j.get("jobType"), posted_at=parse_date(j.get("postedAt")),
                        description=(f"Skills: {', '.join(cats)}\nExperience level: {', '.join(levels)}" if cats else None),
                        raw={"levels": levels, "position": j.get("positionType"), "skills": cats[:12]},
                    )
                for j in arc_jobs:
                    key = j.get("randomKey")
                    title = j.get("title") or ""
                    if not key or key in seen or not title_passes(ctx, title):
                        continue
                    seen.add(key)
                    cats = _categories(j)
                    salary = None
                    if j.get("minAnnualSalary") or j.get("maxAnnualSalary"):
                        salary = f"USD {j.get('minAnnualSalary') or ''}-{j.get('maxAnnualSalary') or ''} /yr"
                    elif j.get("minHourlyRate") or j.get("maxHourlyRate"):
                        salary = f"USD {j.get('minHourlyRate') or ''}-{j.get('maxHourlyRate') or ''} /hr"
                    tz = j.get("timeZone")
                    overlap = j.get("overlapHours")
                    desc = "\n".join(x for x in [
                        "Contract through Arc's vetted network (the client is named after you join Arc).",
                        f"Skills: {', '.join(cats)}" if cats else None,
                        f"Experience level: {j.get('experienceLevel')}" if j.get("experienceLevel") else None,
                        f"Time zone: {tz}" + (f" ({overlap}h overlap required)" if overlap else "") if tz else None,
                    ] if x)
                    yield RawJob(
                        source=self.name, external_id=key, title=title, company_name="Arc (client confidential)",
                        url=f"https://arc.dev/remote-jobs/details/{j.get('urlString')}-{key}", location=_countries(j),
                        remote=True, employment_type=j.get("jobType"), salary_text=salary, description=desc,
                        posted_at=parse_date(j.get("postedAt")),
                        raw={"level": j.get("experienceLevel"), "skills": cats[:12], "arc_exclusive": True},
                    )
                polite_sleep(0.6, 0.6)
