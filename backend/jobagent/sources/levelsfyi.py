"""Levels.fyi jobs through its free, keyless MCP server (https://mcp.levels.fyi/), the interface Levels.fyi publishes
for agents. Its terms forbid scraping the website, so only the MCP is used.

search-jobs returns up to 2 jobs per company and pages by company; get-job adds the full description and is called
only for titles that pass your keywords (a few per run).
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Iterable
from typing import Any

import httpx

from ..utils.http import make_client, polite_sleep
from ..utils.text import parse_date
from .base import RawJob, Source, SourceContext, register, title_passes

MCP = "https://mcp.levels.fyi/"
_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
PAGES = 3
DETAILS_PER_RUN = 15


# The free server allows 20 calls a minute per network (shared with anyone else on it): stay under it, and when it
# still says "try again in N seconds", wait that long once instead of losing the rest of the run.
_MIN_GAP_S = 3.5
_last_call = [0.0]
_RETRY_AFTER = re.compile(r"retryAfterSeconds:\s*(\d+)|try again in (\d+) seconds", re.I)


def call_tool(client: httpx.Client, name: str, arguments: dict[str, Any], *, _retry: bool = True) -> Any:
    """One stateless tools/call, paced under the free limit. The reply is SSE (or JSON); the tool's result is a JSON
    string in content[0].text."""
    wait = _last_call[0] + _MIN_GAP_S - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last_call[0] = time.monotonic()
    try:
        return _call(client, name, arguments)
    except RuntimeError as e:
        m = _RETRY_AFTER.search(str(e))
        if not (_retry and m):
            raise
        time.sleep(min(60, int(m.group(1) or m.group(2))) + 1)
        return call_tool(client, name, arguments, _retry=False)


def _call(client: httpx.Client, name: str, arguments: dict[str, Any]) -> Any:
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}}
    r = client.post(MCP, json=body, headers=_HEADERS)
    if r.status_code >= 400:
        raise RuntimeError(f"HTTP {r.status_code} from Levels.fyi MCP")
    payload: dict[str, Any] | None = None
    if "text/event-stream" in r.headers.get("content-type", ""):
        for line in r.text.splitlines():
            if line.startswith("data:"):
                payload = json.loads(line[5:].strip())
                break
    else:
        payload = r.json()
    result = (payload or {}).get("result") or {}
    text = ((result.get("content") or [{}])[0]).get("text") or ""
    if result.get("isError"):
        raise RuntimeError(f"Levels.fyi MCP error: {text[:200]}")
    return json.loads(text) if text else {}


def salary_text(j: dict[str, Any]) -> str | None:
    rng = j.get("baseSalaryRange") or j.get("totalCompensationRange") or {}
    if not (rng.get("min") or rng.get("max")):
        return None
    return f"{rng.get('currency') or 'USD'} {int(rng.get('min') or 0)}-{int(rng.get('max') or 0)} /yr"


@register
class LevelsFyi(Source):
    name = "levelsfyi"
    label = "Levels.fyi jobs"
    kind = "board"
    priority = 2
    description = ("Tech jobs from Levels.fyi's free MCP server: roles in India and remote roles, with pay ranges and the "
                   "employer's own apply link. One search per role; full descriptions for title matches.")

    def fetch(self, ctx: SourceContext) -> Iterable[RawJob]:
        queries: list[dict[str, Any]] = []
        if "in" in {c.lower() for c in ctx.search.countries}:
            queries.append({"locationSlug": "india"})
        if ctx.search.remote_ok:
            queries.append({"workArrangements": ["remote"]})
        if not queries:
            ctx.log("Levels.fyi skipped: no India in your countries and remote is off")
            return
        days = max(1, min(ctx.search.max_age_days, 30))
        seen: set[str] = set()
        details_left = DETAILS_PER_RUN
        with make_client(timeout=max(ctx.settings.source_timeout_s, 60)) as client:
            for term in self.search_terms(ctx, 3):
                for extra in queries:
                    offset: int | None = 0
                    for _ in range(PAGES):
                        args = {"query": term, "postedWithinDays": days, "sortBy": "relevance", "limit": 25,
                                "offset": offset, **extra}
                        try:
                            data = call_tool(client, "search-jobs", args)
                        except Exception as e:
                            ctx.log(f"Levels.fyi {term} {extra}: {e}")
                            break
                        for j in data.get("jobs") or []:
                            jid, title = str(j.get("jobId") or ""), j.get("title") or ""
                            if not jid or jid in seen or not title_passes(ctx, title):
                                continue
                            seen.add(jid)
                            desc, types = None, None
                            if details_left > 0:
                                details_left -= 1
                                try:
                                    full = call_tool(client, "get-job", {"jobId": jid})
                                    desc, types = full.get("description"), full.get("employmentTypes")
                                except Exception as e:
                                    ctx.log(f"Levels.fyi job {jid}: {e}")
                                polite_sleep(0.4, 0.4)
                            mode = j.get("workArrangement")
                            url = j.get("url") or f"https://www.levels.fyi/jobs?jobId={jid}"
                            yield RawJob(
                                source=self.name, external_id=jid, title=title, company_name=j.get("company") or "",
                                url=url, apply_url=j.get("applyUrl") or url, location="; ".join(j.get("locations") or []) or None,
                                remote=True if mode == "remote" else False if mode in ("office", "hybrid") else None,
                                description=desc, posted_at=parse_date(j.get("postedAt")), salary_text=salary_text(j),
                                employment_type=", ".join(t.replace("_", " ") for t in types) if types else None,
                                raw={"work_arrangement": mode, "company_slug": j.get("companySlug")},
                            )
                        offset = data.get("nextOffset")
                        if offset is None:
                            break
                        polite_sleep(0.6, 0.4)
