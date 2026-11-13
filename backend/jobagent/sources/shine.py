"""Shine.com (India) public search pages. Layout is not stable, so the AI extracts the listings."""

from __future__ import annotations

from collections.abc import Iterable

from ..browser import launch_context, new_page
from ..utils.text import detect_remote, slugify
from ._extract import extract_listings, read_job_page
from .base import RawJob, Source, SourceContext, register, title_passes


@register
class Shine(Source):
    name = "shine"
    label = "Shine.com"
    kind = "browser"
    priority = 3
    needs_browser = True
    uses_ai = True
    fragile = True
    default_enabled = False
    description = "Public search pages on shine.com read in a browser and parsed by the AI (costs ~1 AI call per page)."

    def fetch(self, ctx: SourceContext) -> Iterable[RawJob]:
        details_left = ctx.settings.max_detail_fetches_per_run
        seen: set[str] = set()
        with launch_context() as bctx:
            page = new_page(bctx)
            for term in self.search_terms(ctx, 2):
                for where in self.location_terms(ctx, 2):
                    path = f"{slugify(term)}-jobs" + (f"-in-{slugify(where)}" if where else "")
                    url = f"https://www.shine.com/job-search/{path}"
                    try:
                        res = extract_listings(ctx, page, url)
                    except Exception as e:
                        ctx.log(f"Shine {term}/{where}: {e}")
                        continue
                    ctx.log(f"Shine {term}/{where}: {len(res.get('jobs', []))} listings ({res.get('page_kind')})")
                    for j in res.get("jobs", []):
                        if j["url"] in seen:
                            continue
                        seen.add(j["url"])
                        desc = None
                        if details_left > 0 and title_passes(ctx, j.get("title")) and ctx.wants_details(j["url"]):
                            try:
                                desc = read_job_page(page, j["url"]) or None
                                details_left -= 1
                            except Exception:
                                pass
                        yield RawJob(
                            source=self.name, title=j.get("title") or "", company_name=j.get("department") or "",
                            url=j["url"], apply_url=j["url"], location=j.get("location"),
                            remote=detect_remote(j.get("title"), j.get("location"), desc), description=desc,
                        )
