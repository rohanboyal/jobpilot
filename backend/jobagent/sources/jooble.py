"""Jooble aggregator (free API key: https://jooble.org/api/about). Off until a key is set."""

from __future__ import annotations

from collections.abc import Iterable

from ..utils.http import make_client, polite_sleep
from ..utils.text import detect_remote, html_to_text, parse_date
from .base import RawJob, Source, SourceContext, register


@register
class Jooble(Source):
    name = "jooble"
    label = "Jooble (aggregator)"
    kind = "board"
    default_enabled = False
    description = "Aggregator with strong India/EU coverage. Needs JOBAGENT_JOOBLE_API_KEY (free)."

    def fetch(self, ctx: SourceContext) -> Iterable[RawJob]:
        key = ctx.settings.jooble_api_key
        if not key:
            ctx.log("Jooble skipped: no API key configured")
            return
        seen: set[str] = set()
        with make_client(timeout=ctx.settings.source_timeout_s) as client:
            for term in self.search_terms(ctx):
                for where in self.location_terms(ctx, 2):
                    body = {"keywords": term, "location": where, "page": 1}
                    r = client.post(f"https://jooble.org/api/{key}", json=body)
                    if r.status_code >= 400:
                        ctx.log(f"Jooble {term}/{where}: HTTP {r.status_code}")
                        continue
                    for j in r.json().get("jobs", []):
                        jid = str(j.get("id"))
                        if jid in seen:
                            continue
                        seen.add(jid)
                        desc = html_to_text(j.get("snippet"))
                        yield RawJob(
                            source=self.name, external_id=jid, title=j.get("title") or "",
                            company_name=j.get("company") or "", url=j.get("link") or "", apply_url=j.get("link"),
                            location=j.get("location"), remote=detect_remote(j.get("title"), j.get("location"), desc),
                            employment_type=j.get("type"), salary_text=j.get("salary") or None,
                            description=desc, posted_at=parse_date(j.get("updated")),
                            raw={"via": j.get("source")},
                        )
                    polite_sleep(0.5, 0.5)
