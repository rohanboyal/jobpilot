"""Jobgether (remote and remote-first jobs) through the keyless JSON endpoint it publishes for AI agents.

robots.txt explicitly allows /astroapi/ai/jobs.json and asks for a 2-second crawl delay. The list has no description,
so the offer page's JobPosting data is read for jobs whose title passes your keywords (a few per run).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from datetime import timedelta
from typing import Any

import httpx

from ..models import utcnow
from ..utils.http import get, get_json, make_client, polite_sleep
from ..utils.text import html_to_text, parse_date
from .base import RawJob, Source, SourceContext, register, title_passes

API = "https://jobgether.com/astroapi/ai/jobs.json"
PAGES = 3
DETAILS_PER_RUN = 15
_LDJSON = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)


def job_posting(html: str) -> dict[str, Any] | None:
    """The schema.org JobPosting block of an offer page (pages carry several ld+json blocks)."""
    for block in _LDJSON.findall(html or ""):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        for item in data if isinstance(data, list) else [data]:
            if isinstance(item, dict) and item.get("@type") == "JobPosting":
                return item
    return None


def _locations(ctx: SourceContext) -> str:
    return "india,anywhere" if "in" in {c.lower() for c in ctx.search.countries} else "anywhere"


@register
class Jobgether(Source):
    name = "jobgether"
    label = "Jobgether (remote jobs)"
    kind = "board"
    priority = 2
    description = ("Keyless job API that jobgether.com publishes for AI agents: newest remote roles open to India or "
                   "anywhere, one query per role. Descriptions are read from the offer page for title matches.")

    def fetch(self, ctx: SourceContext) -> Iterable[RawJob]:
        if not ctx.search.remote_ok:
            ctx.log("Jobgether skipped: remote_ok is false")
            return
        since = utcnow() - timedelta(days=ctx.search.max_age_days)
        seen: set[str] = set()
        details_left = DETAILS_PER_RUN
        with make_client(timeout=ctx.settings.source_timeout_s) as client:
            for term in self.search_terms(ctx, 3):
                for page in range(1, PAGES + 1):
                    params = {"keyword": term, "locations": _locations(ctx), "sort": "date", "limit": 25, "page": page}
                    try:
                        data = get_json(client, API, params=params)
                    except Exception as e:
                        ctx.log(f"Jobgether {term} p{page}: {e}")
                        break
                    jobs = data.get("jobs") or []
                    too_old = False
                    for j in jobs:
                        posted = parse_date(j.get("postedAt"))
                        if posted and posted < since:
                            too_old = True
                            continue
                        jid, title = str(j.get("id") or ""), j.get("title") or ""
                        if not jid or jid in seen or not title_passes(ctx, title):
                            continue
                        seen.add(jid)
                        url = j.get("url") or f"https://jobgether.com/offer/{jid}"
                        desc, emp = None, j.get("contractType")
                        if details_left > 0:
                            details_left -= 1
                            desc, emp = self._details(client, url, emp, ctx)
                        yield RawJob(
                            source=self.name, external_id=jid, title=title, company_name=j.get("company") or "",
                            url=url, apply_url=url, location=j.get("location") or "Remote",
                            remote=(j.get("remote") or "") != "Hybrid", employment_type=emp,
                            salary_text=j.get("salaryRange") or None, description=desc, posted_at=posted,
                            raw={"remote_type": j.get("remote"), "experience": j.get("experience"),
                                 "functions": j.get("jobFunctions")},
                        )
                    if too_old or not (data.get("pagination") or {}).get("hasMore"):
                        break
                    polite_sleep(2.0, 0.5)     # robots.txt Crawl-delay: 2

    @staticmethod
    def _details(client: httpx.Client, url: str, emp: str | None, ctx: SourceContext) -> tuple[str | None, str | None]:
        try:
            posting = job_posting(get(client, url).text) or {}
        except Exception as e:
            ctx.log(f"Jobgether offer {url}: {e}")
            return None, emp
        finally:
            polite_sleep(2.0, 0.5)
        types = posting.get("employmentType")
        if isinstance(types, list) and types and not emp:
            emp = str(types[0]).replace("_", " ").title()
        return html_to_text(posting.get("description")) or None, emp
