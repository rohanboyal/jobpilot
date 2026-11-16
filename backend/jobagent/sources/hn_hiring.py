"""Hacker News monthly 'Ask HN: Who is hiring?' thread via the Algolia API."""

from __future__ import annotations

import re
from collections.abc import Iterable

from ..utils.http import get_json, make_client
from ..utils.text import detect_remote, html_to_text, parse_date, title_has
from .base import RawJob, Source, SourceContext, register

_SPLIT = re.compile(r"\s*\|\s*")


@register
class HNHiring(Source):
    name = "hn_hiring"
    label = "Hacker News: Who is hiring"
    kind = "board"
    description = "Latest monthly hiring thread; each top-level comment that matches your keywords becomes a job."

    def fetch(self, ctx: SourceContext) -> Iterable[RawJob]:
        with make_client(timeout=max(ctx.settings.source_timeout_s, 60)) as client:
            hits = get_json(client, "https://hn.algolia.com/api/v1/search_by_date",
                            params={"tags": "story,author_whoishiring", "query": "Who is hiring", "hitsPerPage": 10})
            story = next((h for h in hits.get("hits", []) if "who is hiring" in (h.get("title") or "").lower()), None)
            if not story:
                ctx.log("HN: no hiring thread found")
                return
            ctx.log(f"HN thread: {story.get('title')}")
            item = get_json(client, f"https://hn.algolia.com/api/v1/items/{story.get('objectID')}")

        kws = [k.lower() for k in ctx.search.title_keywords if k.strip()]
        skills = [k.lower() for k in ctx.search.skills if k.strip()]
        count = 0
        for c in item.get("children", []):
            html = c.get("text") or ""
            if not html.strip():
                continue
            text = html_to_text(html)
            low = text.lower()
            if kws and not any(title_has(low, k) for k in kws) and not any(s in low for s in skills):
                continue
            first = text.split("\n", 1)[0]
            parts = [p.strip() for p in _SPLIT.split(first) if p.strip()]
            company = parts[0] if parts else "Unknown (HN)"
            title = next((p for p in parts[1:] if any(k in p.lower() for k in kws)), None) or (parts[1] if len(parts) > 1 else first[:120])
            location = next((p for p in parts[1:] if re.search(r"remote|onsite|hybrid|,|[A-Z][a-z]+ ?(?:[A-Z]{2})?", p) and p != title), None)
            url = f"https://news.ycombinator.com/item?id={c.get('id')}"
            yield RawJob(
                source=self.name,
                external_id=str(c.get("id")),
                title=title[:280],
                company_name=company[:190],
                url=url,
                apply_url=None,          # HN posts are usually 'email us'; handled as a manual application
                location=location,
                remote=detect_remote(first, location, text),
                description=text,
                posted_at=parse_date(c.get("created_at")),
                raw={"thread": story.get("title"), "header": first[:300]},
            )
            count += 1
            if count >= ctx.settings.max_jobs_per_source_run:
                break
