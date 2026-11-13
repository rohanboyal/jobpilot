"""Direct company careers pages (ats: custom). Browser + AI extraction; auto-upgrades to an ATS adapter when
the page turns out to link to Greenhouse/Lever/Ashby/Workable/SmartRecruiters."""

from __future__ import annotations

from collections.abc import Iterable

from ..browser import launch_context, new_page
from ..models import utcnow
from ..utils.text import detect_remote
from ._extract import extract_listings, read_job_page
from .ats_detect import detect_ats
from .base import RawJob, Source, SourceContext, register, title_passes


@register
class CompanyCareers(Source):
    name = "company_careers"
    label = "Company careers pages"
    kind = "browser"
    priority = 1
    needs_browser = True
    uses_ai = True
    description = "Tracked companies without a known ATS: their careers page is read in a browser and parsed by the AI."

    def fetch(self, ctx: SourceContext) -> Iterable[RawJob]:
        companies = [c for c in ctx.companies if c.is_active and c.ats_type in ("custom", "unknown") and c.careers_url]
        companies = companies[: ctx.settings.max_company_pages_per_run]
        if not companies:
            ctx.log("Company careers: nothing to crawl (add careers_url to companies with ats: custom)")
            return
        ctx.log(f"Company careers: {len(companies)} pages")
        details_left = ctx.settings.max_detail_fetches_per_run
        with launch_context() as bctx:
            page = new_page(bctx)
            for company in companies:
                try:
                    res = extract_listings(ctx, page, company.careers_url)
                except Exception as e:
                    company.last_error = f"{type(e).__name__}: {str(e)[:300]}"
                    ctx.bump("company_errors")
                    ctx.log(f"  ! {company.name}: {company.last_error}")
                    continue
                company.last_crawled_at = utcnow()
                company.last_error = None if res.get("page_kind") != "blocked" else "blocked by bot protection"
                jobs = res.get("jobs", [])
                # If the page links straight into a known ATS, remember that so the fast adapter takes over next run.
                for j in jobs:
                    ats = detect_ats(j.get("url"))
                    if ats:
                        company.ats_type, company.ats_slug = ats
                        company.notes = (company.notes or "") + f"\nauto-detected {ats[0]} board '{ats[1]}'"
                        ctx.log(f"  {company.name}: detected {ats[0]} board '{ats[1]}'; future runs use the API")
                        break
                ctx.log(f"  {company.name}: {len(jobs)} listings ({res.get('page_kind')})")
                for j in jobs:
                    title = j.get("title") or ""
                    desc = None
                    if details_left > 0 and title_passes(ctx, title):
                        try:
                            desc = read_job_page(page, j["url"]) or None
                            details_left -= 1
                        except Exception:
                            desc = None
                    yield RawJob(
                        source=self.name, title=title, company_name=company.name, url=j["url"], apply_url=j["url"],
                        location=j.get("location"), remote=detect_remote(title, j.get("location"), desc),
                        description=desc, company_id=company.id, company_website=company.website,
                        raw={"department": j.get("department"), "careers_url": company.careers_url},
                    )
