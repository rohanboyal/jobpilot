"""Naukri.com via your own browser profile (India). Reads the search results page; descriptions for title matches."""

from __future__ import annotations

from collections.abc import Iterable

from ..browser import dismiss_cookie_banners, launch_context, looks_blocked, new_page
from ..utils.text import detect_remote, parse_date, slugify
from ._extract import extract_listings, read_job_page
from .base import RawJob, Source, SourceContext, register, title_passes

_CARDS_JS = """
() => Array.from(document.querySelectorAll('div.srp-jobtuple-wrapper, article.jobTuple, div.cust-job-tuple')).map(c => {
  const a = c.querySelector('a.title, a.jobTitle, a[title]');
  const comp = c.querySelector('a.comp-name, a.subTitle, .comp-name');
  const loc = c.querySelector('.locWdth, .loc span, .location, [title*=","]');
  const exp = c.querySelector('.expwdth, .exp span, .experience');
  const sal = c.querySelector('.sal-wrap span, .salary');
  const date = c.querySelector('.job-post-day, .postedDate, .type span');
  const snip = c.querySelector('.job-desc, .job-description, .ellipsis');
  return a ? { href: a.href, title: (a.getAttribute('title') || a.textContent || '').trim(),
    company: comp ? comp.textContent.trim() : '', location: loc ? loc.textContent.trim() : '',
    experience: exp ? exp.textContent.trim() : '', salary: sal ? sal.textContent.trim() : '',
    date: date ? date.textContent.trim() : '', snippet: snip ? snip.textContent.trim() : '' } : null;
}).filter(Boolean)
"""


@register
class Naukri(Source):
    name = "naukri"
    label = "Naukri (your browser)"
    kind = "browser"
    priority = 3
    needs_browser = True
    uses_ai = True
    fragile = True
    default_enabled = False
    description = "Searches naukri.com in a saved Chromium profile; falls back to AI extraction if the layout changes."

    def fetch(self, ctx: SourceContext) -> Iterable[RawJob]:
        details_left = ctx.settings.max_detail_fetches_per_run
        seen: set[str] = set()
        with launch_context() as bctx:
            page = new_page(bctx)
            for term in self.search_terms(ctx, 3):
                for where in self.location_terms(ctx, 2):
                    slug = f"{slugify(term)}-jobs" + (f"-in-{slugify(where)}" if where else "")
                    url = f"https://www.naukri.com/{slug}?jobAge={min(ctx.search.max_age_days, 30)}"
                    try:
                        page.goto(url, wait_until="domcontentloaded")
                        page.wait_for_timeout(3000)
                        dismiss_cookie_banners(page)
                    except Exception as e:
                        ctx.log(f"Naukri {term}/{where}: {e}")
                        continue
                    if looks_blocked(page):
                        ctx.bump("blocked")
                        ctx.log("Naukri: bot check shown. Run `jobagent browser-login naukri` once in a visible window.")
                        return
                    cards = page.evaluate(_CARDS_JS)
                    if not cards:
                        res = extract_listings(ctx, page, url)
                        cards = [{"href": j["url"], "title": j.get("title", ""), "company": "", "location": j.get("location", "")}
                                 for j in res.get("jobs", [])]
                        ctx.log(f"Naukri {term}/{where}: layout unknown, the AI extracted {len(cards)}")
                    for c in cards:
                        href = c.get("href")
                        if not href or href in seen:
                            continue
                        seen.add(href)
                        desc = c.get("snippet") or None
                        if details_left > 0 and title_passes(ctx, c.get("title")) and ctx.wants_details(href):
                            try:
                                desc = read_job_page(page, href) or desc
                                details_left -= 1
                            except Exception:
                                pass
                        yield RawJob(
                            source=self.name, title=c.get("title") or "", company_name=c.get("company") or "",
                            url=href, apply_url=href, location=c.get("location") or None,
                            remote=detect_remote(c.get("title"), c.get("location"), desc),
                            salary_text=c.get("salary") or None, description=desc,
                            posted_at=parse_date(c.get("date")),
                            raw={"experience": c.get("experience")},
                        )
                    page.wait_for_timeout(1500)
