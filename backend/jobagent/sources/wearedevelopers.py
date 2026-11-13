"""WeAreDevelopers (EU + US) through the Markdown view of its job search that the site documents for agents.

Every page supports `.md` (see wearedevelopers.com/agents.md). The site has no India listings, so this source only runs
when your profiles include one of its countries.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from ..utils.http import get, make_client, polite_sleep
from ..utils.text import parse_date
from .base import RawJob, Source, SourceContext, register, title_passes

SEARCH = "https://www.wearedevelopers.com/jobs.md"
COUNTRIES = {"at", "be", "de", "es", "fr", "gb", "it", "nl", "pt", "se", "us"}
PAGES = 2
DETAILS_PER_RUN = 15
_LINK = re.compile(r"\[(View job|Apply)\]\((https?://[^)\s]+)\)")
_FIELD = re.compile(r"^- \*\*(\w[\w ]*):\*\*\s*(.+)$")
_ID = re.compile(r"/jobs/(ext/)?(\d+)")


def parse_markdown(md: str) -> list[dict[str, Any]]:
    """Split the search Markdown into job dicts: title, company, location, salary, contract, published, url, apply."""
    jobs: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    for line in (md or "").splitlines():
        if line.startswith("## "):
            cur = {"title": line[3:].strip()}
            jobs.append(cur)
            continue
        if cur is None:
            continue
        m = _FIELD.match(line.strip())
        if m:
            cur[m.group(1).strip().lower()] = m.group(2).strip()
            continue
        for label, url in _LINK.findall(line):
            cur["url" if label == "View job" else "apply"] = url
    return [j for j in jobs if j.get("url")]


def detail_text(md: str) -> str:
    """The job page Markdown without the 'Markdown version of …' banner."""
    body = (md or "").split("\n---\n", 1)[-1]
    return body.strip()


@register
class WeAreDevelopers(Source):
    name = "wearedevelopers"
    label = "WeAreDevelopers (EU / US)"
    kind = "board"
    priority = 2
    description = ("Developer jobs in Europe and the US from wearedevelopers.com, read through the Markdown view it offers "
                   "agents. Runs only when your profiles include one of its countries (de, gb, fr, nl, us, …).")

    def fetch(self, ctx: SourceContext) -> Iterable[RawJob]:
        wanted = [c.lower() for c in ctx.search.countries if c.lower() in COUNTRIES]
        if not wanted:
            ctx.log("WeAreDevelopers skipped: none of your countries is covered (it lists EU and US jobs)")
            return
        seen: set[str] = set()
        details_left = DETAILS_PER_RUN
        with make_client(timeout=ctx.settings.source_timeout_s) as client:
            for country in wanted[:3]:
                for term in self.search_terms(ctx, 2):
                    for page in range(1, PAGES + 1):
                        try:
                            md = get(client, SEARCH, params={"q": term, "country": country.upper(), "page": page}).text
                        except Exception as e:
                            ctx.log(f"WeAreDevelopers {country}/{term} p{page}: {e}")
                            break
                        jobs = parse_markdown(md)
                        for j in jobs:
                            m = _ID.search(j["url"])
                            ext = (f"ext-{m.group(2)}" if m.group(1) else m.group(2)) if m else j["url"]
                            if ext in seen or not title_passes(ctx, j["title"]):
                                continue
                            seen.add(ext)
                            desc = None
                            if details_left > 0:
                                details_left -= 1
                                try:
                                    desc = detail_text(get(client, j["url"] + ".md").text) or None
                                except Exception as e:
                                    ctx.log(f"WeAreDevelopers job {ext}: {e}")
                                polite_sleep(0.5, 0.5)
                            location = j.get("location") or ""
                            remote = "(remote available)" in location.lower()
                            yield RawJob(
                                source=self.name, external_id=ext, title=j["title"], company_name=j.get("company") or "",
                                url=j["url"], apply_url=j.get("apply") or j["url"],
                                location=re.sub(r"\s*\(remote available\)", "", location, flags=re.I) or None,
                                remote=remote or None, salary_text=j.get("salary"), employment_type=j.get("contract"),
                                posted_at=parse_date(j.get("published")), description=desc,
                                raw={"country": country, "experience": j.get("experience")},
                            )
                        if len(jobs) < 24 or "page=" + str(page + 1) not in md:
                            break
                        polite_sleep(1.0, 0.5)
