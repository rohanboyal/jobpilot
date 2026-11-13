"""Adzuna aggregator (free developer key: https://developer.adzuna.com). Off until keys are set."""

from __future__ import annotations

from collections.abc import Iterable

from ..utils.http import get_json, make_client, polite_sleep
from ..utils.text import detect_remote, parse_date
from .base import RawJob, Source, SourceContext, register


@register
class Adzuna(Source):
    name = "adzuna"
    label = "Adzuna (aggregator)"
    kind = "board"
    default_enabled = False
    description = "Aggregates thousands of boards per country. Needs JOBAGENT_ADZUNA_APP_ID / _APP_KEY (free)."

    def fetch(self, ctx: SourceContext) -> Iterable[RawJob]:
        s = ctx.settings
        if not (s.adzuna_app_id and s.adzuna_app_key):
            ctx.log("Adzuna skipped: no API key configured")
            return
        seen: set[str] = set()
        with make_client(timeout=s.source_timeout_s) as client:
            for country in ctx.search.countries or ["in"]:
                for term in self.search_terms(ctx):
                    for where in self.location_terms(ctx, 2):
                        params = {
                            "app_id": s.adzuna_app_id, "app_key": s.adzuna_app_key,
                            "what": term, "results_per_page": 50, "max_days_old": ctx.search.max_age_days,
                            "sort_by": "date", "content-type": "application/json",
                        }
                        if where:
                            params["where"] = where
                        url = f"https://api.adzuna.com/v1/api/jobs/{country.lower()}/search/1"
                        try:
                            data = get_json(client, url, params=params)
                        except Exception as e:
                            ctx.log(f"Adzuna {country}/{term}/{where}: {e}")
                            continue
                        for j in data.get("results", []):
                            jid = str(j.get("id"))
                            if jid in seen:
                                continue
                            seen.add(jid)
                            location = (j.get("location") or {}).get("display_name")
                            sal = None
                            if j.get("salary_min") or j.get("salary_max"):
                                sal = f"{int(j.get('salary_min') or 0)}-{int(j.get('salary_max') or 0)} /yr"
                            yield RawJob(
                                source=self.name, external_id=jid,
                                title=j.get("title") or "",
                                company_name=(j.get("company") or {}).get("display_name") or "",
                                url=j.get("redirect_url") or "", apply_url=j.get("redirect_url"),
                                location=location, remote=detect_remote(j.get("title"), location, j.get("description")),
                                employment_type=j.get("contract_time"), salary_text=sal,
                                description=j.get("description"), posted_at=parse_date(j.get("created")),
                                raw={"category": (j.get("category") or {}).get("label")},
                            )
                        polite_sleep(0.3, 0.3)
