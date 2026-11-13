"""Crossover through the anonymous JSON endpoint its jobs page uses. Off by default: Crossover's website terms forbid
automated access, and the live board is mostly US education roles."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from ..utils.http import get_json, make_client
from .base import RawJob, Source, SourceContext, register, title_passes

API = "https://profile-api.crossover.com/pipelines"


def _location(rec: dict[str, Any]) -> str | None:
    work_locations = (rec.get("Work_Locations__r") or {}).get("records") or []
    names = [(w.get("Location__r") or {}).get("Name") for w in work_locations]
    names = [n for n in names if n]
    if names:
        return ", ".join(names)
    if rec.get("Work_Country__c"):
        return rec["Work_Country__c"]
    return "Worldwide" if rec.get("Geographic_Restriction__c") == "Global" else None


@register
class Crossover(Source):
    name = "crossover"
    label = "Crossover"
    kind = "board"
    priority = 3
    default_enabled = False
    fragile = True
    description = ("Crossover's active hiring pipelines (USD-paid, worldwide or region-restricted). Off by default: the "
                   "website terms forbid automated access and the board is currently mostly US education roles.")

    def fetch(self, ctx: SourceContext) -> Iterable[RawJob]:
        with make_client(timeout=ctx.settings.source_timeout_s) as client:
            data = get_json(client, API, params={"status": "Active"})
        for rec in data.get("records") or []:
            title = rec.get("Name") or ""
            url = rec.get("DisplayUrl") or ""
            if not url or not title_passes(ctx, title):
                continue
            brand = (rec.get("Brand__r") or {}).get("Name") or "Crossover"
            model = rec.get("Work_Model__c")
            salary = None
            if rec.get("Yearly_Rate__c"):
                salary = f"USD {int(rec['Yearly_Rate__c'])} /yr"
            elif rec.get("Hourly_Rate__c"):
                salary = f"USD {int(rec['Hourly_Rate__c'])} /hr"
            desc = "\n".join(x for x in [
                f"{brand} ({rec.get('Family') or 'n/a'}) hiring through Crossover.",
                f"Work model: {model}" if model else None,
                f"Geographic restriction: {rec.get('Geographic_Restriction__c')}" if rec.get("Geographic_Restriction__c") else None,
                f"{rec.get('Job_Type__c')}, {rec.get('Hours_per_Week__c')} h/week" if rec.get("Job_Type__c") else None,
            ] if x)
            yield RawJob(
                source=self.name, external_id=str(rec.get("ProductCode") or ""), title=title, company_name=brand,
                url=url, apply_url=rec.get("Apply_URL__c") or url, location=_location(rec),
                remote=(model == "Remote") if model else None, employment_type=rec.get("Job_Type__c"),
                salary_text=salary, description=desc, raw={"family": rec.get("Family"), "work_model": model},
            )
