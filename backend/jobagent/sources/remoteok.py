from __future__ import annotations

from collections.abc import Iterable

from ..utils.http import get_json, make_client
from ..utils.text import fix_mojibake, html_to_text, parse_date
from .base import RawJob, Source, SourceContext, register


@register
class RemoteOK(Source):
    name = "remoteok"
    label = "RemoteOK"
    kind = "board"
    description = "Public JSON feed of remoteok.com, filtered by your title keywords."

    def fetch(self, ctx: SourceContext) -> Iterable[RawJob]:
        if not ctx.search.remote_ok:
            ctx.log("RemoteOK skipped: remote_ok is false")
            return
        with make_client(timeout=ctx.settings.source_timeout_s) as client:
            data = get_json(client, "https://remoteok.com/api")
        kws = [k.lower() for k in ctx.search.title_keywords if k.strip()]
        skills = [k.lower() for k in ctx.search.skills if k.strip()]
        for j in data:
            if not isinstance(j, dict) or "position" not in j:
                continue  # first element is a legal notice
            title = fix_mojibake(j.get("position") or "")
            tags = [t.lower() for t in (j.get("tags") or [])]
            hay = title.lower()
            if kws and not (any(k in hay for k in kws) or any(s in tags for s in skills)):
                continue
            sal = None
            if j.get("salary_min") or j.get("salary_max"):
                sal = f"USD {j.get('salary_min', '')}-{j.get('salary_max', '')}"
            yield RawJob(
                source=self.name,
                external_id=str(j.get("id") or j.get("slug")),
                title=title,
                company_name=fix_mojibake(j.get("company") or ""),
                url=j.get("url") or f"https://remoteok.com/remote-jobs/{j.get('slug')}",
                apply_url=j.get("apply_url") or j.get("url"),
                location=fix_mojibake(j.get("location") or "Remote"),
                remote=True,
                salary_text=sal,
                description=fix_mojibake(html_to_text(j.get("description"))),
                posted_at=parse_date(j.get("epoch") or j.get("date")),
                raw={"tags": j.get("tags")},
            )
