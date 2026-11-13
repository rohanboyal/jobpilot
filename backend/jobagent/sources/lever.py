from __future__ import annotations

from ..models import Company
from ..utils.http import get_json, make_client
from ..utils.text import detect_remote, html_to_text, parse_date
from .base import ATSSource, RawJob, SourceContext, register


@register
class Lever(ATSSource):
    name = "lever"
    label = "Lever boards"
    ats_type = "lever"
    description = "Public postings API (api.lever.co) of tracked companies."

    def fetch_company(self, ctx: SourceContext, company: Company) -> list[RawJob]:
        url = f"https://api.lever.co/v0/postings/{company.ats_slug}"
        with make_client(timeout=ctx.settings.source_timeout_s) as client:
            data = get_json(client, url, params={"mode": "json"})
        out: list[RawJob] = []
        for j in data:
            cats = j.get("categories") or {}
            location = cats.get("location") or ", ".join(cats.get("allLocations") or []) or None
            parts = [j.get("descriptionPlain") or html_to_text(j.get("description"))]
            for lst in j.get("lists") or []:
                parts.append(f"\n{lst.get('text', '')}\n{html_to_text(lst.get('content'))}")
            if j.get("additionalPlain") or j.get("additional"):
                parts.append(j.get("additionalPlain") or html_to_text(j.get("additional")))
            desc = "\n".join(p for p in parts if p).strip()
            wp = (j.get("workplaceType") or "").lower()
            remote = True if wp == "remote" else (False if wp in {"onsite", "hybrid"} else None)
            out.append(RawJob(
                source=self.name,
                external_id=str(j.get("id")),
                title=j.get("text") or "",
                company_name=company.name,
                url=j.get("hostedUrl") or url,
                apply_url=j.get("applyUrl") or (j.get("hostedUrl") or "").rstrip("/") + "/apply",
                location=location,
                remote=remote if remote is not None else detect_remote(j.get("text"), location, desc),
                employment_type=cats.get("commitment"),
                description=desc,
                posted_at=parse_date(j.get("createdAt")),
                salary_text=_salary(j.get("salaryRange")),
                raw={"team": cats.get("team"), "department": cats.get("department"), "workplaceType": wp},
            ))
        return out


def _salary(r: dict | None) -> str | None:
    if not r or not (r.get("min") or r.get("max")):
        return None
    cur = r.get("currency") or ""
    return f"{cur} {r.get('min', '')}-{r.get('max', '')} {r.get('interval', '')}".strip()
