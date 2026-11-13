from __future__ import annotations

from collections.abc import Iterable
from datetime import timedelta

from sqlalchemy import select

from ..models import Run, utcnow
from ..utils.http import get_json, make_client
from ..utils.text import html_to_text, parse_date
from .base import RawJob, Source, SourceContext, register, title_passes


@register
class Remotive(Source):
    name = "remotive"
    label = "Remotive (remote jobs)"
    kind = "board"
    description = "Public feed of remotive.com (a small fixed sample; the API ignores search terms). Fetched at most every 6 hours."

    def fetch(self, ctx: SourceContext) -> Iterable[RawJob]:
        if not ctx.search.remote_ok:
            ctx.log("Remotive skipped: remote_ok is false")
            return
        # The feed's own notice asks for a handful of calls per day.
        if ctx.db is not None:
            last = ctx.db.scalars(select(Run).where(Run.kind == "crawl", Run.source == self.name, Run.status.in_(["ok", "partial"]),
                                                    Run.finished_at.is_not(None)).order_by(Run.finished_at.desc())).first()
            if last and last.finished_at and utcnow() - last.finished_at < timedelta(hours=6):
                ctx.log("Remotive skipped: fetched less than 6 hours ago")
                return
        with make_client(timeout=ctx.settings.source_timeout_s) as client:
            data = get_json(client, "https://remotive.com/api/remote-jobs")
        skills = [s.lower() for s in ctx.search.skills if s.strip()]
        for j in data.get("jobs", []):
            title = j.get("title") or ""
            tags = [t.lower() for t in (j.get("tags") or [])]
            if not title_passes(ctx, title) and not any(s in tags for s in skills):
                continue
            yield RawJob(
                source=self.name,
                external_id=str(j.get("id")),
                title=title,
                company_name=j.get("company_name") or "",
                url=j.get("url") or "",
                apply_url=j.get("url"),
                location=j.get("candidate_required_location") or "Remote",
                remote=True,
                employment_type=j.get("job_type"),
                salary_text=j.get("salary") or None,
                description=html_to_text(j.get("description")),
                posted_at=parse_date(j.get("publication_date")),
                raw={"category": j.get("category"), "tags": j.get("tags")},
            )
