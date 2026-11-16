"""Source adapter contract + registry.

A Source turns the user's search profile (and, for ATS sources, the tracked companies) into RawJob records.
Adapters never touch the database directly except through the SourceContext helpers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta  # noqa: F401
from typing import Any, ClassVar

from sqlalchemy.orm import Session

from ..config import SearchProfile, Settings
from ..models import Company, utcnow


@dataclass
class RawJob:
    source: str
    title: str
    company_name: str
    url: str
    external_id: str | None = None
    location: str | None = None
    remote: bool | None = None
    description: str | None = None          # plain text (adapters convert HTML)
    apply_url: str | None = None
    posted_at: datetime | None = None
    employment_type: str | None = None
    salary_text: str | None = None
    company_website: str | None = None
    ats_type: str | None = None
    ats_slug: str | None = None
    company_id: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class SourceContext:
    settings: Settings
    search: SearchProfile
    db: Session
    log: Callable[[str], None]
    companies: list[Company] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)
    truncated_company_ids: set[int] = field(default_factory=set)   # boards we did not read to the end
    known_urls: set[str] = field(default_factory=set)              # signed-in sites: job pages already read
    profiles: int = 1                       # profiles merged into `search`: each gets at least its top title searched

    def bump(self, key: str, n: int = 1) -> None:
        self.stats[key] = self.stats.get(key, 0) + n

    def wants_details(self, url: str | None) -> bool:
        return url not in self.known_urls


class Source(ABC):
    name: ClassVar[str] = "base"
    label: ClassVar[str] = "Base"
    kind: ClassVar[str] = "board"              # ats | board | browser
    priority: ClassVar[int] = 2                # lower wins when the same role is seen on several sources
    needs_browser: ClassVar[bool] = False
    uses_ai: ClassVar[bool] = False
    default_enabled: ClassVar[bool] = True
    description: ClassVar[str] = ""
    fragile: ClassVar[bool] = False            # scraping a site that may block; best effort

    @abstractmethod
    def fetch(self, ctx: SourceContext) -> Iterable[RawJob]: ...

    # Helpers available to all adapters -------------------------------------------------
    @staticmethod
    def search_terms(ctx: SourceContext, max_terms: int = 4) -> list[str]:
        terms = [r for r in ctx.search.roles if r.strip()]
        return terms[:max(max_terms, ctx.profiles)] or ["software engineer"]

    @staticmethod
    def location_terms(ctx: SourceContext, max_terms: int = 3) -> list[str]:
        locs = [loc for loc in ctx.search.locations if loc.strip() and loc.strip().lower() != "remote"]
        return locs[:max_terms] or [""]


class ATSSource(Source):
    """Iterates the tracked companies whose ats_type matches `ats_type` and fetches each board."""

    kind: ClassVar[str] = "ats"
    priority: ClassVar[int] = 1
    ats_type: ClassVar[str] = ""

    @abstractmethod
    def fetch_company(self, ctx: SourceContext, company: Company) -> list[RawJob]: ...

    def fetch(self, ctx: SourceContext) -> Iterable[RawJob]:
        companies = [c for c in ctx.companies if c.is_active and c.ats_type == self.ats_type and c.ats_slug]
        ctx.log(f"{self.label}: {len(companies)} companies")
        for company in companies:
            try:
                jobs = self.fetch_company(ctx, company)
            except Exception as e:  # one bad slug must not stop the run
                company.last_error = f"{type(e).__name__}: {str(e)[:300]}"
                ctx.bump("company_errors")
                ctx.log(f"  ! {company.name}: {company.last_error}")
                if getattr(e, "status", None) == 404:   # no board under that name: pause it instead of failing every run
                    company.is_active = False
                    note = (f"Paused {utcnow():%Y-%m-%d}: its {self.label} board '{company.ats_slug}' was not found (404). "
                            "Fix the board name and turn it on again, or delete it.")
                    company.notes = f"{company.notes}\n{note}".strip() if company.notes else note
                    ctx.bump("companies_paused")
                    ctx.log(f"    paused {company.name}: no {self.label} board '{company.ats_slug}'")
                continue
            company.last_error = None
            company.last_crawled_at = utcnow()
            ctx.bump("companies_ok")
            if len(jobs) >= ctx.settings.max_jobs_per_source_run:
                ctx.bump("truncated")
                ctx.truncated_company_ids.add(company.id)
                ctx.log(f"  {company.name}: {len(jobs)} jobs (hit the per-board cap; expiry skipped for this company)")
            else:
                ctx.log(f"  {company.name}: {len(jobs)} jobs")
            for j in jobs:
                j.company_id = company.id
                j.ats_type = self.ats_type
                j.ats_slug = company.ats_slug
                j.company_website = j.company_website or company.website
                yield j


_REGISTRY: dict[str, type[Source]] = {}


def register(cls: type[Source]) -> type[Source]:
    _REGISTRY[cls.name] = cls
    return cls


def all_sources() -> dict[str, type[Source]]:
    from . import load_all  # noqa: F401

    load_all()
    return dict(_REGISTRY)


def get_source(name: str) -> Source:
    sources = all_sources()
    if name not in sources:
        raise KeyError(f"unknown source '{name}'. Known: {', '.join(sorted(sources))}")
    return sources[name]()


# ---------------------------------------------------------------------------
# Cheap title gate shared by adapters that need a second request per job.
# ---------------------------------------------------------------------------


def title_passes(ctx: SourceContext, title: str | None) -> bool:
    t = (title or "").lower()
    if not t:
        return False
    if any(x.lower() in t for x in ctx.search.exclude_keywords if x.strip()):
        return False
    kws = [k.lower() for k in ctx.search.title_keywords if k.strip()]
    from ..utils.text import title_has

    return True if not kws else any(title_has(t, k) for k in kws)


def fetched_within(ctx: SourceContext, source_name: str, hours: float) -> bool:
    """True when the last successful crawl of `source_name` finished less than `hours` ago.

    Feeds that ask for infrequent polling use this to skip a run. Without a database (tests, harness) it is False.
    """
    if ctx.db is None:
        return False
    from sqlalchemy import select

    from ..models import Run

    last = ctx.db.scalars(
        select(Run).where(Run.kind == "crawl", Run.source == source_name, Run.status.in_(["ok", "partial"]),
                          Run.finished_at.is_not(None)).order_by(Run.finished_at.desc())
    ).first()
    return bool(last and last.finished_at and utcnow() - last.finished_at < timedelta(hours=hours))


def skill_hit(ctx: SourceContext, *texts: str | None) -> bool:
    """True when any configured skill appears in any of the given texts (tags, excerpts)."""
    skills = [s.lower() for s in ctx.search.skills if s.strip()]
    hay = " ".join(t.lower() for t in texts if t)
    return any(s in hay for s in skills)
