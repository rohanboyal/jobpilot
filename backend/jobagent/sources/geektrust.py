"""Geektrust (India): the jobs page's own keyless JSON endpoint, one small GET per role family."""

from __future__ import annotations

import re
from collections.abc import Iterable

from ..utils.http import get_json, make_client, polite_sleep
from .base import RawJob, Source, SourceContext, register, title_passes

API = "https://www.geektrust.com/api/v2/jobs"
ROLES = ("BACKEND", "FULLSTACK", "DEVOPS", "DATAENGINEER")
_HEADERS = {"Accept": "application/json", "Referer": "https://www.geektrust.com/jobs"}
_VIA = re.compile(r"\s*\(?via geektrust\)?\s*$", re.I)


@register
class Geektrust(Source):
    name = "geektrust"
    label = "Geektrust"
    kind = "board"
    priority = 2
    fragile = True
    description = ("Curated India product-company roles (geektrust.com) read from the site's own JSON endpoint; no login, "
                   "no key. Postings carry tech, experience range and sometimes salary, but no full description.")

    def fetch(self, ctx: SourceContext) -> Iterable[RawJob]:
        if "in" not in {c.lower() for c in ctx.search.countries}:
            ctx.log("Geektrust skipped: 'in' is not in your countries")
            return
        seen: set[str] = set()
        with make_client(timeout=ctx.settings.source_timeout_s) as client:
            for role in ROLES:
                try:
                    data = get_json(client, API, params={"role": role}, headers=_HEADERS)
                except Exception as e:
                    ctx.log(f"Geektrust {role}: {e}")
                    continue
                if not isinstance(data, list):
                    ctx.log(f"Geektrust {role}: unexpected payload")
                    continue
                for j in data:
                    jid = str(j.get("jobRoleId") or "")
                    title = (j.get("jobTitle") or "").strip()
                    if not jid or jid in seen or not title_passes(ctx, title):
                        continue
                    seen.add(jid)
                    yrs = j.get("yrsOfExp") or {}
                    tech = [t.get("name") for t in (j.get("primaryTech") or []) if t.get("name")]
                    locs = [loc.get("name") for loc in (j.get("jobLocations") or []) if loc.get("name")]
                    sal = j.get("salary") or {}
                    salary = None
                    if sal.get("showToCandidates") and (sal.get("max") or sal.get("min")):
                        salary = f"INR {sal.get('min') or ''}-{sal.get('max') or ''} LPA"
                    desc = "\n".join(x for x in [
                        j.get("companyDefinition"),
                        f"Company type: {j.get('companyType')}" if j.get("companyType") else None,
                        f"Primary tech: {', '.join(tech)}" if tech else None,
                        f"Experience: {yrs.get('min', '?')}-{yrs.get('max', '?')} years" if yrs else None,
                        f"Remote: {j.get('jobRemotePreference')}" if j.get("jobRemotePreference") else None,
                    ] if x)
                    yield RawJob(
                        source=self.name, external_id=jid, title=title,
                        company_name=_VIA.sub("", j.get("companyName") or "").strip(),
                        url=f"https://www.geektrust.com/candidates/jobs/{j.get('companyTitle')}/{jid}",
                        location=", ".join(locs) or None, remote=j.get("jobRemotePreference") == "Open to Remote",
                        salary_text=salary, description=desc or None,
                        raw={"role": role, "years": yrs, "tech": tech[:10], "company_type": j.get("companyType")},
                    )
                polite_sleep(0.4, 0.4)
