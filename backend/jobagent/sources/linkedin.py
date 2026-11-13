"""LinkedIn public job search (the guest endpoints the logged-out jobs page uses). No account involved.

Best effort: LinkedIn rate-limits anonymous traffic, so we page shallowly (10 results per page), sleep between
requests, fetch descriptions only for title matches and back off on 429s. The public job page is login-walled for
applying, so these jobs are prepared as manual applications unless an external apply link is found.
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterable

from bs4 import BeautifulSoup

from ..utils.http import HttpError, get, make_client, polite_sleep
from ..utils.text import detect_remote, html_to_text, normalize_ws, parse_date
from .ats_detect import detect_ats
from .base import RawJob, Source, SourceContext, register, title_passes

SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
DETAIL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{id}"
PAGE_SIZE = 10
PAGES = 3

_HEADERS = {"Accept": "text/html,*/*;q=0.8", "Referer": "https://www.linkedin.com/jobs/search/"}


@register
class LinkedIn(Source):
    name = "linkedin"
    label = "LinkedIn jobs (public)"
    kind = "board"
    priority = 3
    fragile = True
    description = "Public job search results plus descriptions from the public job page. Applying needs your LinkedIn login, so these become manual applications."

    def fetch(self, ctx: SourceContext) -> Iterable[RawJob]:
        age_s = max(1, ctx.search.max_age_days) * 86400
        seen: set[str] = set()
        details_left = ctx.settings.max_detail_fetches_per_run
        consecutive_429 = 0
        with make_client(timeout=ctx.settings.source_timeout_s, headers=_HEADERS) as client:
            for term in self.search_terms(ctx, 3):
                for where in self.location_terms(ctx, 2) + (["Remote"] if ctx.search.remote_ok else []):
                    for start in range(0, PAGE_SIZE * PAGES, PAGE_SIZE):
                        params = {"keywords": term, "location": where or "", "f_TPR": f"r{age_s}", "start": start, "sortBy": "DD"}
                        if where == "Remote":
                            params.update({"f_WT": "2", "location": ctx.search.locations[0] if ctx.search.locations else ""})
                        try:
                            r = get(client, SEARCH, params=params, retries=2)
                        except HttpError as e:
                            if e.status == 429:
                                ctx.bump("throttled")
                                ctx.log("LinkedIn: search throttled (429); stopping early")
                                return
                            ctx.log(f"LinkedIn search {term}/{where}: {e}")
                            break
                        except Exception as e:
                            ctx.log(f"LinkedIn search {term}/{where}: {e}")
                            break
                        cards = _parse_cards(r.text)
                        if not cards:
                            break
                        for c in cards:
                            if c["id"] in seen:
                                continue
                            seen.add(c["id"])
                            desc = apply_url = None
                            extra: dict = {}
                            if details_left > 0 and title_passes(ctx, c["title"]):
                                try:
                                    dr = get(client, DETAIL.format(id=c["id"]), retries=2)
                                    desc, apply_url, extra = _parse_detail(dr.text)
                                    details_left -= 1
                                    consecutive_429 = 0
                                    polite_sleep(0.8, 0.8)
                                except HttpError as e:
                                    if e.status == 429:
                                        consecutive_429 += 1
                                        ctx.bump("throttled")
                                        if consecutive_429 >= 3:
                                            ctx.log("LinkedIn: detail pages throttled repeatedly; continuing without descriptions")
                                            details_left = 0
                                        else:
                                            time.sleep(12 * consecutive_429)
                                    else:
                                        ctx.log(f"LinkedIn detail {c['id']}: {e}")
                                except Exception as e:
                                    ctx.log(f"LinkedIn detail {c['id']}: {e}")
                            ats = detect_ats(apply_url)
                            yield RawJob(
                                source=self.name, external_id=c["id"], title=c["title"],
                                company_name=c["company"], url=c["url"],
                                apply_url=apply_url or c["url"], location=c["location"],
                                remote=detect_remote(c["title"], c["location"], desc),
                                description=desc, posted_at=parse_date(c["posted"]),
                                ats_type=ats[0] if ats else None, ats_slug=ats[1] if ats else None,
                                raw={"company_url": c["company_url"], "apply_external": bool(apply_url), **extra},
                            )
                        if len(cards) < PAGE_SIZE:
                            break
                        polite_sleep(1.2, 1.0)


def _parse_cards(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    out = []
    for card in soup.select("div.base-card, li > div.base-search-card"):
        urn = card.get("data-entity-urn") or ""
        m = re.search(r"(\d+)$", urn)
        link = card.select_one("a.base-card__full-link, a.base-search-card__full-link")
        href = link.get("href") if link else None
        if not m and href:
            m = re.search(r"-(\d+)\?", href) or re.search(r"/view/(\d+)", href)
        if not m:
            continue
        title = card.select_one("h3.base-search-card__title")
        company_link = card.select_one("h4.base-search-card__subtitle a")
        company = company_link or card.select_one("h4.base-search-card__subtitle")
        loc = card.select_one("span.job-search-card__location")
        time_el = card.select_one("time")
        out.append({
            "id": m.group(1),
            "title": normalize_ws(title.get_text()) if title else "",
            "company": normalize_ws(company.get_text()) if company else "",
            "company_url": (company_link.get("href") or "").split("?")[0] or None if company_link else None,
            "location": normalize_ws(loc.get_text()) if loc else None,
            "posted": (time_el.get("datetime") if time_el else None) or (normalize_ws(time_el.get_text()) if time_el else None),
            "url": f"https://www.linkedin.com/jobs/view/{m.group(1)}",
        })
    return out


def _parse_detail(html: str) -> tuple[str | None, str | None, dict]:
    soup = BeautifulSoup(html, "lxml")
    body = soup.select_one("div.show-more-less-html__markup") or soup.select_one("div.description__text")
    if body is not None:
        for btn in body.select("button.show-more-less-html__button"):
            btn.decompose()
    desc = html_to_text(str(body)) if body else None
    apply_url = None
    code = soup.select_one("code#applyUrl")
    if code:
        m = re.search(r'"(https?://[^"]+)"', code.decode_contents())
        if m:
            apply_url = _unwrap_redirect(m.group(1))
    extra: dict = {}
    for li in soup.select("li.description__job-criteria-item"):
        k = li.select_one("h3")
        v = li.select_one("span")
        if k and v:
            extra[normalize_ws(k.get_text()).lower().replace(" ", "_")] = normalize_ws(v.get_text())
    applicants = soup.select_one("span.num-applicants__caption, figcaption.num-applicants__caption")
    if applicants:
        extra["applicants"] = normalize_ws(applicants.get_text())
    return desc, apply_url, extra


def _unwrap_redirect(url: str) -> str:
    from urllib.parse import parse_qs, unquote, urlsplit

    try:
        p = urlsplit(url)
        if "linkedin.com" in p.netloc and ("/redir/" in p.path or "/jobs/view/externalApply/" in p.path):
            q = parse_qs(p.query)
            if q.get("url"):
                return unquote(q["url"][0])
    except ValueError:
        pass
    return url
