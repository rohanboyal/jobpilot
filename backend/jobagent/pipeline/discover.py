"""Find more companies to crawl: web search for ATS boards and careers pages matching your roles."""

from __future__ import annotations

import re
from collections.abc import Callable
from urllib.parse import parse_qs, unquote, urlsplit

from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import cancel
from ..models import Company, Run, utcnow
from ..profiles import active_search
from ..sources.ats_detect import detect_ats
from ..utils.http import make_client, polite_sleep
from ..utils.text import domain_of

DDG = "https://html.duckduckgo.com/html/"
ATS_HOSTS = ["boards.greenhouse.io", "job-boards.greenhouse.io", "jobs.lever.co", "jobs.ashbyhq.com",
             "apply.workable.com", "jobs.smartrecruiters.com"]
_JOB_BOARD_HOSTS = ("linkedin.", "indeed.", "naukri.", "glassdoor.", "instahyre.", "cutshort.", "wellfound.",
                    "foundit.", "shine.", "timesjobs.", "hirist.", "iimjobs.", "monster.", "ziprecruiter.", "dice.",
                    "simplyhired.", "jooble.", "adzuna.", "internshala.", "unstop.", "youtube.", "reddit.", "quora.",
                    "github.", "medium.", "facebook.", "twitter.", "x.com", "wikipedia.",
                    "weekday.works", "startup.jobs", "builtin.", "dynamitejobs.", "aijobs.", "mljobs.", "apna.co",
                    "careerbuilder.", "turing.", "uplers.", "welcometothejungle.", "ventureloop.", "techfetch.",
                    "remote.co", "ziprecruiter.", "hasjob.", "geektrust.", "himalayas.app", "workingnomads.",
                    "jobspresso.", "nodesk.co", "weworkremotely.", "jobicy.", "arbeitnow.", "arc.dev", "crossover.",
                    "dice.", "80000hours.", "justremote.", "themuse.", "flexjobs.", "upwork.", "fiverr.", "freelancer.",
                    "toptal.", "google.")
_CAREERS_PATH = re.compile(r"/(careers?|jobs?|join(-us)?|openings|work-with-us|vacanc|opportunit)", re.I)

_PROBE = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}",
    "lever": "https://api.lever.co/v0/postings/{slug}?mode=json&limit=1",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}",
    "workable": "https://apply.workable.com/api/v1/widget/accounts/{slug}",
    "smartrecruiters": "https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=1",
}


class SearchThrottled(RuntimeError):
    pass


def ddg_search(client, query: str, max_results: int = 20) -> list[dict[str, str]]:
    r = client.post(DDG, data={"q": query, "kl": "wt-wt"})
    if r.status_code in (202, 403, 429) or "anomaly" in r.text[:3000].lower():
        raise SearchThrottled(f"search engine throttled (HTTP {r.status_code})")
    soup = BeautifulSoup(r.text, "lxml")
    out = []
    for a in soup.select("a.result__a"):
        href = a.get("href") or ""
        if "uddg=" in href:
            href = unquote(parse_qs(urlsplit(href).query).get("uddg", [href])[0])
        if href.startswith("http"):
            out.append({"title": a.get_text(" ", strip=True), "url": href})
        if len(out) >= max_results:
            break
    return out


def probe_ats(client, ats: str, slug: str) -> tuple[bool, str | None]:
    url = _PROBE[ats].format(slug=slug)
    try:
        r = client.get(url)
    except Exception:
        return False, None
    if r.status_code != 200:
        return False, None
    name = None
    try:
        data = r.json()
        if ats == "greenhouse":
            name = data.get("name")
        elif ats == "workable":
            name = data.get("name")
        elif ats == "smartrecruiters":
            content = data.get("content") or []
            if not content or int(data.get("totalFound") or 0) <= 0:
                return False, None   # the API answers 200 with an empty page for unknown identifiers
            name = (content[0].get("company") or {}).get("name")
    except ValueError:
        pass
    return True, name


def _pretty(slug: str) -> str:
    return re.sub(r"[-_]+", " ", slug).strip().title()


def discover_companies(db: Session, log: Callable[[str], None] | None = None, max_new: int = 30) -> dict:
    search = active_search(db)
    run = Run(kind="discover", source="web_search", status="running")
    db.add(run)
    db.commit()
    lines: list[str] = []

    def _log(m: str) -> None:
        lines.append(m)
        if log:
            log(m)

    stats = {"queries": 0, "candidates": 0, "added_ats": 0, "added_custom": 0, "known": 0, "probe_failed": 0}
    roles = [r for r in search.roles if r.strip()][:3]
    loc = next((x for x in search.locations if x.strip() and x.lower() != "remote"), "")
    existing = {(c.ats_type, (c.ats_slug or "").lower()) for c in db.scalars(select(Company)).all()}
    existing_domains = {c.domain for c in db.scalars(select(Company)).all() if c.domain}
    added = 0
    error = None
    try:
        with make_client(timeout=30) as client:
            for role in roles:
                queries = [f'"{role}" site:{h}' + (f' "{loc}"' if loc else "") for h in ATS_HOSTS]
                queries.append(f'"{role}" careers "{loc}" "we are hiring"' if loc else f'"{role}" careers "we are hiring"')
                for q in queries:
                    if added >= max_new or cancel.requested():
                        break
                    try:
                        results = ddg_search(client, q)
                    except SearchThrottled as e:
                        _log(f"! {e}; stopping discovery for now")
                        raise
                    stats["queries"] += 1
                    _log(f"{q}  → {len(results)} results")
                    for res in results:
                        url = res["url"]
                        ats = detect_ats(url)
                        if ats:
                            key = (ats[0], ats[1].lower())
                            if key in existing:
                                stats["known"] += 1
                                continue
                            stats["candidates"] += 1
                            ok, name = probe_ats(client, *ats)
                            if not ok:
                                stats["probe_failed"] += 1
                                existing.add(key)
                                continue
                            db.add(Company(name=name or _pretty(ats[1]), ats_type=ats[0], ats_slug=ats[1], origin="discovered",
                                           notes=f"found via search: {q}"))
                            existing.add(key)
                            added += 1
                            stats["added_ats"] += 1
                            _log(f"  + {name or _pretty(ats[1])} ({ats[0]}:{ats[1]})")
                        else:
                            host = urlsplit(url).netloc.lower()
                            if any(b in host for b in _JOB_BOARD_HOSTS) or not _CAREERS_PATH.search(urlsplit(url).path):
                                continue
                            dom = domain_of(url)
                            if not dom or dom in existing_domains:
                                continue
                            stats["candidates"] += 1
                            name = re.sub(r"\s*[-|–:].*$", "", res["title"]).strip()[:120] or _pretty(dom.split(".")[0])
                            db.add(Company(name=name, ats_type="custom", careers_url=url, website=f"https://{dom}", domain=dom,
                                           origin="discovered", notes=f"found via search: {q}"))
                            existing_domains.add(dom)
                            added += 1
                            stats["added_custom"] += 1
                            _log(f"  + {name} (careers page {url})")
                        if added >= max_new:
                            break
                    db.commit()
                    polite_sleep(1.5, 1.5)
    except SearchThrottled as e:
        error = str(e)
    except Exception as e:
        db.rollback()
        error = f"{type(e).__name__}: {e}"
        _log("! " + error)
    run.finished_at = utcnow()
    run.stats = stats
    run.error = error
    run.log = "\n".join(lines)[-30000:]
    run.status = "ok" if not error else ("partial" if added else "error")
    db.commit()
    return {**stats, "error": error}
