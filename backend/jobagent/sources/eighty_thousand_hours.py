"""80,000 Hours job board (impact-focused organisations) through its public Algolia index.

The search-only key is published in the board's own HTML; it is re-read from the homepage on every run so a rotated
key does not break the source.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import timedelta

import httpx

from ..models import utcnow
from ..utils.http import get, get_json, make_client, polite_sleep
from ..utils.text import html_to_text, parse_date
from .base import RawJob, Source, SourceContext, register, skill_hit, title_passes

HOME = "https://jobs.80000hours.org/"
DEFAULT_APP, DEFAULT_KEY, INDEX = "W6KM1UDIB3", "d1d7f2c8696e7b36837d5ed337c4a319", "jobs_prod"
_APP = re.compile(r'algoliaApplicationId\s*[:=]\s*"([A-Z0-9]{8,12})"')
_KEY = re.compile(r'algoliaApiKey\s*[:=]\s*"([0-9a-f]{32})"')


def algolia_credentials(client: httpx.Client) -> tuple[str, str]:
    try:
        html = get(client, HOME).text
        app, key = _APP.search(html), _KEY.search(html)
        if app and key:
            return app.group(1), key.group(1)
    except Exception:
        pass
    return DEFAULT_APP, DEFAULT_KEY


@register
class EightyThousandHours(Source):
    name = "eighty_thousand_hours"
    label = "80,000 Hours job board"
    kind = "board"
    priority = 2
    description = ("Public search index of jobs.80000hours.org (impact, AI-safety, global-health organisations; a large "
                   "remote-global slice). Postings within your max age whose title matches your keywords, or software "
                   "roles mentioning your skills.")

    def fetch(self, ctx: SourceContext) -> Iterable[RawJob]:
        since = int((utcnow() - timedelta(days=ctx.search.max_age_days)).timestamp())
        with make_client(timeout=ctx.settings.source_timeout_s) as client:
            app, key = algolia_credentials(client)
            headers = {"X-Algolia-Application-Id": app, "X-Algolia-API-Key": key}
            page = 0
            while True:
                params = {"query": "", "hitsPerPage": 1000, "page": page, "numericFilters": f"posted_at>={since}",
                          "attributesToHighlight": ""}
                data = get_json(client, f"https://{app}-dsn.algolia.net/1/indexes/{INDEX}", params=params, headers=headers)
                hits = data.get("hits") or []
                ctx.log(f"80,000 Hours: page {page + 1}/{data.get('nbPages', 1)}, {len(hits)} postings since {ctx.search.max_age_days} days")
                for h in hits:
                    title = h.get("title") or ""
                    skills = h.get("tags_skill") or []
                    software = any("software" in s.lower() for s in skills)
                    if not title_passes(ctx, title) and not (software and skill_hit(ctx, h.get("description_short"), h.get("description"))):
                        continue
                    pk = h.get("post_pk") or h.get("objectID")
                    countries = h.get("tags_country") or []
                    cities = h.get("tags_city") or []
                    remote = any("remote" in x.lower() for x in (h.get("tags_location_type") or []) + countries + cities)
                    yield RawJob(
                        source=self.name, external_id=str(pk), title=title, company_name=h.get("company_name") or "",
                        url=f"https://jobs.80000hours.org/?jobPk={pk}", apply_url=h.get("url_external") or None,
                        location=", ".join(cities or countries) or None, remote=remote,
                        employment_type=", ".join(h.get("tags_role_type") or []) or None, salary_text=h.get("salary") or None,
                        description=html_to_text(h.get("description") or h.get("description_short")),
                        posted_at=parse_date(h.get("posted_at")), company_website=h.get("company_url") or None,
                        raw={"areas": h.get("tags_area"), "experience": h.get("tags_exp_required"),
                             "closes_at": h.get("closes_at"), "skills": skills},
                    )
                page += 1
                if page >= int(data.get("nbPages") or 1):
                    break
                polite_sleep(0.5, 0.5)
