"""Dice (US tech board) through its official, keyless MCP endpoint (JSON-RPC over HTTP).

Dice's site terms forbid crawling the HTML pages, and the MCP tool text asks that results be used for discovery
only, so jobs from here are prepared as manual applications (you apply on dice.com yourself). Off by default:
the board is US-centric; add "us" to your countries and enable it to use it.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

import httpx

from ..utils.http import make_client, polite_sleep
from ..utils.text import parse_date
from .base import RawJob, Source, SourceContext, register, title_passes

MCP = "https://mcp.dice.com/mcp"
_HEADERS = {"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-11-25"}
PER_PAGE = 50
PAGES = 2


def search_jobs(client: httpx.Client, keyword: str, page: int, posted: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """One search_jobs tool call; returns (jobs, metadata). The reply is SSE or plain JSON."""
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "search_jobs", "arguments": {
                "keyword": keyword, "jobs_per_page": PER_PAGE, "page_number": page, "sort": "datePosted", "posted_date": posted}}}
    r = client.post(MCP, json=body, headers=_HEADERS)
    if r.status_code >= 400:
        raise RuntimeError(f"HTTP {r.status_code} from Dice MCP")
    payload: dict[str, Any] | None = None
    if "text/event-stream" in r.headers.get("content-type", ""):
        for line in r.text.splitlines():
            if line.startswith("data:"):
                payload = json.loads(line[5:].strip())
                break
    else:
        payload = r.json()
    result = (payload or {}).get("result") or {}
    if result.get("isError"):
        raise RuntimeError(f"Dice MCP error: {str(result.get('content'))[:200]}")
    structured = result.get("structuredContent") or {}
    return structured.get("data") or [], structured.get("metadata") or {}


@register
class Dice(Source):
    name = "dice"
    label = "Dice (US tech jobs)"
    kind = "board"
    priority = 2
    default_enabled = False
    fragile = True
    description = ("Official keyless MCP search of dice.com (US contract-heavy tech board). Discovery only per Dice's "
                   "terms: applications are prepared as manual. Needs 'us' in your countries.")

    def fetch(self, ctx: SourceContext) -> Iterable[RawJob]:
        if "us" not in {c.lower() for c in ctx.search.countries}:
            ctx.log("Dice skipped: add 'us' to your countries to search this US board")
            return
        days = ctx.search.max_age_days
        posted = "ONE" if days <= 1 else "THREE" if days <= 3 else "SEVEN"
        seen: set[str] = set()
        with make_client(timeout=max(ctx.settings.source_timeout_s, 60)) as client:
            for term in self.search_terms(ctx, 3):
                for page in range(1, PAGES + 1):
                    try:
                        jobs, meta = search_jobs(client, term, page, posted)
                    except Exception as e:
                        ctx.log(f"Dice {term} p{page}: {e}")
                        break
                    for j in jobs:
                        guid = j.get("guid") or j.get("id")
                        title = j.get("title") or ""
                        if not guid or guid in seen or not title_passes(ctx, title):
                            continue
                        seen.add(guid)
                        url = (j.get("detailsPageUrl") or "").split("?")[0] or f"https://www.dice.com/job-detail/{guid}"
                        salary = j.get("salary")
                        yield RawJob(
                            source=self.name, external_id=str(guid), title=title, company_name=j.get("companyName") or "",
                            url=url, apply_url=url,
                            location=j.get("jobLocation") or ("Remote (US)" if j.get("isRemote") else None),
                            remote=bool(j.get("isRemote")), employment_type=j.get("employmentType"),
                            salary_text=salary if salary and "depends" not in salary.lower() else None,
                            description=j.get("summary"), posted_at=parse_date(j.get("postedDate")),
                            raw={"employer_type": j.get("employerType"), "sponsor": j.get("willingToSponsor"),
                                 "workplace": j.get("workplaceTypes"), "easy_apply": j.get("easyApply")},
                        )
                    if len(jobs) < PER_PAGE or page >= int(meta.get("totalPages") or 1):
                        break
                    polite_sleep(0.8, 0.6)
