"""Indeed via your own browser profile. Sign in once with `jobagent browser-login indeed`; after that the saved
session is reused headlessly. Volume is kept low on purpose."""

from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import urlencode

from ..browser import dismiss_cookie_banners, launch_context, looks_blocked, new_page
from ..utils.text import detect_remote, normalize_ws, parse_date
from .base import RawJob, Source, SourceContext, register, title_passes

_DOMAINS = {"in": "in.indeed.com", "us": "www.indeed.com", "gb": "uk.indeed.com", "uk": "uk.indeed.com",
            "ca": "ca.indeed.com", "au": "au.indeed.com", "de": "de.indeed.com", "sg": "sg.indeed.com",
            "ae": "ae.indeed.com", "nl": "nl.indeed.com", "fr": "fr.indeed.com"}

_CARDS_JS = """
() => Array.from(document.querySelectorAll('div.job_seen_beacon, [data-testid="slider_item"], li .cardOutline')).map(c => {
  const a = c.querySelector('h2.jobTitle a, a.jcs-JobTitle, a[data-jk]');
  const t = c.querySelector('h2.jobTitle span[title], h2.jobTitle a span, h2.jobTitle');
  const comp = c.querySelector('[data-testid="company-name"], .companyName');
  const loc = c.querySelector('[data-testid="text-location"], .companyLocation');
  const date = c.querySelector('[data-testid="myJobsStateDate"], .date');
  const snip = c.querySelector('[data-testid="jobsnippet_footer"], .job-snippet, [class*="snippet"]');
  const sal = c.querySelector('[data-testid="attribute_snippet_testid"], .salary-snippet-container, .estimated-salary');
  return a ? { jk: a.getAttribute('data-jk') || (a.href.match(/jk=([a-z0-9]+)/i) || [])[1] || null,
    href: a.href, title: (t && (t.getAttribute('title') || t.textContent) || '').trim(),
    company: comp ? comp.textContent.trim() : '', location: loc ? loc.textContent.trim() : '',
    date: date ? date.textContent.trim() : '', snippet: snip ? snip.textContent.trim() : '',
    salary: sal ? sal.textContent.trim() : '' } : null;
}).filter(Boolean)
"""


@register
class Indeed(Source):
    name = "indeed"
    label = "Indeed (your browser)"
    kind = "browser"
    priority = 3
    needs_browser = True
    fragile = True
    default_enabled = False
    description = "Searches Indeed in a saved Chromium profile. Run `jobagent browser-login indeed` once if it gets blocked."

    def fetch(self, ctx: SourceContext) -> Iterable[RawJob]:
        details_left = ctx.settings.max_detail_fetches_per_run
        seen: set[str] = set()
        with launch_context() as bctx:
            page = new_page(bctx)
            for country in (ctx.search.countries or ["in"])[:2]:
                host = _DOMAINS.get(country.lower(), "www.indeed.com")
                for term in self.search_terms(ctx, 3):
                    for where in self.location_terms(ctx, 2):
                        for start in (0, 10):
                            q = {"q": term, "l": where, "fromage": min(ctx.search.max_age_days, 14), "sort": "date", "start": start}
                            url = f"https://{host}/jobs?{urlencode(q)}"
                            try:
                                page.goto(url, wait_until="domcontentloaded")
                                page.wait_for_timeout(2500)
                                dismiss_cookie_banners(page)
                            except Exception as e:
                                ctx.log(f"Indeed {term}/{where}: {e}")
                                break
                            if looks_blocked(page):
                                ctx.bump("blocked")
                                ctx.log("Indeed: bot check shown. Run `jobagent browser-login indeed` once in a visible window.")
                                return
                            cards = page.evaluate(_CARDS_JS)
                            if not cards:
                                break
                            for c in cards:
                                jk = c.get("jk") or c.get("href")
                                if not jk or jk in seen:
                                    continue
                                seen.add(jk)
                                job_url = f"https://{host}/viewjob?jk={c['jk']}" if c.get("jk") else c["href"]
                                desc = c.get("snippet") or None
                                if details_left > 0 and title_passes(ctx, c["title"]) and ctx.wants_details(job_url):
                                    try:
                                        page.goto(job_url, wait_until="domcontentloaded")
                                        page.wait_for_timeout(1500)
                                        if not looks_blocked(page):
                                            desc = page.locator("#jobDescriptionText").inner_text(timeout=6000) or desc
                                        details_left -= 1
                                    except Exception:
                                        pass
                                yield RawJob(
                                    source=self.name, external_id=c.get("jk"), title=c["title"],
                                    company_name=c.get("company") or "", url=job_url, apply_url=job_url,
                                    location=c.get("location") or None,
                                    remote=detect_remote(c["title"], c.get("location"), desc),
                                    salary_text=normalize_ws(c.get("salary")) or None,
                                    description=desc, posted_at=parse_date(c.get("date")),
                                    raw={"host": host},
                                )
                            page.wait_for_timeout(1500)
