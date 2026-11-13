"""The Muse through its official public jobs API (keyless: 500 requests an hour).

The API terms ask apps to link back to themuse.com (job URLs are The Muse landing pages) and forbid scraping the site,
so only the API is used. Results are not reliably date-ordered and include old postings, so a few pages are read per
query and filtered by your maximum job age. The listing is paged, so it never drives expiry.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import timedelta

from ..models import utcnow
from ..utils.http import get_json, make_client, polite_sleep
from ..utils.text import html_to_text, parse_date
from .base import RawJob, Source, SourceContext, register, title_passes

API = "https://www.themuse.com/api/public/jobs"
CATEGORIES = ("Software Engineering", "Data and Analytics")
PAGES = 6
_LEVELS = {"intern": "Internship", "junior": "Entry Level", "mid": "Mid Level", "senior": "Senior Level"}


def location_names(ctx: SourceContext) -> list[str]:
    """The Muse writes Indian cities as 'Bangalore, India'; remote roles are 'Flexible / Remote'."""
    out: list[str] = []
    if "in" in {c.lower() for c in ctx.search.countries}:
        for loc in ctx.search.locations:
            name = loc.strip()
            if name and name.lower() not in ("india", "remote", "anywhere"):
                out.append(f"{name}, India")
    return out


@register
class TheMuse(Source):
    name = "themuse"
    label = "The Muse"
    kind = "board"
    priority = 2
    description = ("Official public API of themuse.com: software and data roles in your Indian cities and fully remote ones, "
                   "filtered by your seniority and maximum job age.")

    def fetch(self, ctx: SourceContext) -> Iterable[RawJob]:
        queries: list[list[str]] = []
        cities = location_names(ctx)
        if cities:
            queries.append(cities)
        if ctx.search.remote_ok:
            queries.append(["Flexible / Remote"])
        if not queries:
            ctx.log("The Muse skipped: no Indian cities in your profiles and remote is off")
            return
        levels = [_LEVELS[s] for s in ctx.search.seniority if s in _LEVELS]
        since = utcnow() - timedelta(days=ctx.search.max_age_days)
        seen: set[str] = set()
        with make_client(timeout=ctx.settings.source_timeout_s) as client:
            for locations in queries:
                for page in range(PAGES):
                    params: list[tuple[str, str]] = [("page", str(page))]
                    params += [("category", c) for c in CATEGORIES] + [("location", loc) for loc in locations]
                    params += [("level", lv) for lv in levels]
                    try:
                        data = get_json(client, API, params=params)
                    except Exception as e:
                        ctx.log(f"The Muse {locations[0]} p{page}: {e}")
                        break
                    results = data.get("results") or []
                    for j in results:
                        posted = parse_date(j.get("publication_date"))
                        jid, title = str(j.get("id") or ""), j.get("name") or ""
                        if not jid or jid in seen or (posted and posted < since) or not title_passes(ctx, title):
                            continue
                        seen.add(jid)
                        places = [x.get("name") for x in (j.get("locations") or []) if x.get("name")]
                        url = (j.get("refs") or {}).get("landing_page") or f"https://www.themuse.com/jobs/{jid}"
                        yield RawJob(
                            source=self.name, external_id=jid, title=title,
                            company_name=(j.get("company") or {}).get("name") or "", url=url, apply_url=url,
                            location="; ".join(places) or None, remote=any("remote" in p.lower() for p in places) or None,
                            description=html_to_text(j.get("contents")) or None, posted_at=posted,
                            raw={"levels": [x.get("name") for x in j.get("levels") or []],
                                 "categories": [x.get("name") for x in j.get("categories") or []]},
                        )
                    if page + 1 >= int(data.get("page_count") or 0):
                        break
                    polite_sleep(0.6, 0.4)
