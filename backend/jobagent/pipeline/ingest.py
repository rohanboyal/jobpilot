"""Turn RawJobs from a source into Job rows: normalize, dedup, link companies, expire closed postings."""

from __future__ import annotations

import traceback
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import cancel, pacing
from ..config import get_settings
from ..models import Company, Job, JobStatus, Run, utcnow
from ..profiles import enabled_profiles, merge
from ..settings_store import enabled_sources
from ..sources.base import RawJob, SourceContext, all_sources, get_source
from ..utils.dedup import dedup_key, fingerprint
from ..utils.text import domain_of, normalize_ws, truncate

_ACTIVE_FOR_DUP = {JobStatus.NEW, JobStatus.QUEUED, JobStatus.FILTERED_OUT, JobStatus.SCORED, JobStatus.SHORTLISTED}
_OWNS_APPLICATION = {JobStatus.APPLYING, JobStatus.APPLIED}
_CARRIES_VERDICT = (JobStatus.SCORED, JobStatus.SHORTLISTED, JobStatus.REJECTED)


def _resolve_company(db: Session, raw: RawJob, cache: dict[str, Company]) -> Company | None:
    if raw.company_id:
        key = f"id:{raw.company_id}"
        if key not in cache:
            c = db.get(Company, raw.company_id)
            if c:
                cache[key] = c
        return cache.get(key)
    name = normalize_ws(raw.company_name)
    if raw.ats_type and raw.ats_slug:
        key = f"ats:{raw.ats_type}:{raw.ats_slug}"
        if key not in cache:
            c = db.scalars(select(Company).where(Company.ats_type == raw.ats_type, Company.ats_slug == raw.ats_slug)).first()
            if c is None and name:
                c = Company(name=name, ats_type=raw.ats_type, ats_slug=raw.ats_slug, origin="job",
                            website=raw.company_website, domain=domain_of(raw.company_website))
                db.add(c)
                db.flush()
            if c:
                cache[key] = c
        return cache.get(key)
    if not name:
        return None
    key = f"name:{name.lower()}"
    if key not in cache:
        c = db.scalars(select(Company).where(Company.name.ilike(name))).first()
        if c is None:
            c = Company(name=name, ats_type="unknown", origin="job", website=raw.company_website,
                        domain=domain_of(raw.company_website))
            db.add(c)
            db.flush()
        cache[key] = c
    c = cache[key]
    if raw.company_website and not c.website:
        c.website = raw.company_website
        c.domain = domain_of(raw.company_website)
    return c


# ---------------------------------------------------------------------------
# Cross-source duplicates
# ---------------------------------------------------------------------------


def _is_parked(job: Job) -> bool:
    return (job.status == JobStatus.FILTERED_OUT and bool(job.prefilter_reasons)
            and str(job.prefilter_reasons[0]).startswith("duplicate of"))


def _park(loser: Job, winner: Job, stats: dict[str, int]) -> None:
    """Hide `loser` behind `winner` (same role, better source). Carry a AI verdict across if the winner has none."""
    loser.duplicate_of = winner.id
    if winner.fit_score is None and loser.fit_score is not None:
        winner.fit_score, winner.fit, winner.scored_at = loser.fit_score, loser.fit, loser.scored_at
        winner.trust_score, winner.trust_flags = loser.trust_score, loser.trust_flags
        if winner.status == JobStatus.NEW and loser.status in _CARRIES_VERDICT:
            winner.status = loser.status
    if loser.status in _ACTIVE_FOR_DUP:
        loser.status = JobStatus.FILTERED_OUT
        loser.prefilter_reasons = [f"duplicate of #{winner.id} ({winner.source})"]
    stats["duplicates"] = stats.get("duplicates", 0) + 1


def _unpark(job: Job) -> None:
    job.duplicate_of = None
    if _is_parked(job):
        job.status, job.prefilter_reasons = JobStatus.NEW, None


def _mark_duplicates(db: Session, job: Job, priority: int, priorities: dict[str, int], stats: dict[str, int]) -> None:
    """Same role seen on another source: keep one visible row (company ATS > job board > scraped site).

    Two postings on the same board are never duplicates of each other, an expired row never wins, and a row the
    user applied through always wins.
    """
    others = db.scalars(select(Job).where(Job.dedup_key == job.dedup_key, Job.id != job.id,
                                          Job.source != job.source)).all()
    job_owns = job.status in _OWNS_APPLICATION
    for other in others:
        if other.duplicate_of == job.id:
            continue
        if job.duplicate_of == other.id and other.status != JobStatus.EXPIRED:
            continue
        other_owns = other.status in _OWNS_APPLICATION
        other_live = other.status != JobStatus.EXPIRED
        if other_owns and not job_owns:
            _park(job, other, stats)
            return
        if job_owns and other_owns:
            continue
        if not job_owns and other_live and priorities.get(other.source, 2) <= priority:
            _park(job, other, stats)
            return
        # this row wins: take over and retire the other
        _unpark(job)
        _park(other, job, stats)


def ingest_raw(db: Session, raw: RawJob, priority: int, priorities: dict[str, int], stats: dict[str, int],
               cache: dict[str, Company]) -> Job | None:
    title = normalize_ws(raw.title)
    if not title or not raw.url:
        stats["skipped_invalid"] = stats.get("skipped_invalid", 0) + 1
        return None
    company = _resolve_company(db, raw, cache)
    company_name = normalize_ws(raw.company_name) or (company.name if company else "Unknown")
    fp = fingerprint(source=raw.source, external_id=raw.external_id, url=raw.url, company=company_name,
                     title=title, location=raw.location)
    now = utcnow()
    job = db.scalars(select(Job).where(Job.fingerprint == fp)).first()
    if job is None:
        job = Job(
            fingerprint=fp, dedup_key=dedup_key(company_name, title, raw.location), source=raw.source,
            external_id=raw.external_id, company_id=company.id if company else None, company_name=company_name,
            title=title[:300], location=truncate(normalize_ws(raw.location), 300) or None, remote=raw.remote,
            employment_type=raw.employment_type, salary_text=truncate(raw.salary_text, 200) or None,
            description=raw.description, url=raw.url[:1000], apply_url=(raw.apply_url or raw.url)[:1000],
            posted_at=raw.posted_at, discovered_at=now, last_seen_at=now, status=JobStatus.NEW, raw=raw.raw or None,
        )
        db.add(job)
        db.flush()
        stats["new"] = stats.get("new", 0) + 1
    else:
        job.last_seen_at = now
        if raw.description and (not job.description or len(raw.description) > len(job.description) + 200):
            job.description = raw.description
        if raw.posted_at and not job.posted_at:
            job.posted_at = raw.posted_at
        if raw.apply_url and (not job.apply_url or job.apply_url == job.url):
            job.apply_url = raw.apply_url[:1000]
        if raw.salary_text and not job.salary_text:
            job.salary_text = truncate(raw.salary_text, 200)
        if job.status == JobStatus.EXPIRED:
            # Back on the board: pick up where it was (scored, shortlisted, …) instead of being re-scored as new.
            job.status = job.expired_from or JobStatus.NEW
            job.expired_from = None
        if company and not job.company_id:
            job.company_id = company.id
        stats["updated"] = stats.get("updated", 0) + 1
    _mark_duplicates(db, job, priority, priorities, stats)
    return job


def run_source(name: str, db: Session, log: Callable[[str], None] | None = None,
               company_ids: Iterable[int] | None = None, manual: bool = False,
               profile_ids: list[int] | None = None) -> Run:
    """manual: the user asked for this source by name, so a signed-in site's rest and daily limit don't apply.
    profile_ids: search for these profiles only (None = every enabled one)."""
    settings = get_settings()
    selected = enabled_profiles(db, profile_ids)
    search = merge([p for _, p in selected])
    covered = [pid for pid, _ in selected]
    source = get_source(name)
    priorities = {n: c.priority for n, c in all_sources().items()}
    run = Run(kind="crawl", source=name, status="running")
    db.add(run)
    db.commit()
    lines: list[str] = []

    def _log(msg: str) -> None:
        line = f"{datetime.now():%H:%M:%S} {msg}"
        lines.append(line)
        if log:
            log(line)

    stmt = select(Company).where(Company.is_active.is_(True))
    if company_ids is not None:
        stmt = stmt.where(Company.id.in_(list(company_ids)))
    companies = db.scalars(stmt).all()
    careful = source.needs_browser and name in pacing.signed_in_sites(db)
    skip = pacing.skip_reason(db, name, covered) if careful and not manual else None
    if careful:
        settings = settings.model_copy(update={
            "max_detail_fetches_per_run": min(settings.max_detail_fetches_per_run, pacing.DETAIL_PAGES)})
    ctx = SourceContext(settings=settings, search=search, db=db, log=_log, companies=companies,
                        known_urls=pacing.known_urls(db, name) if careful else set(), profiles=max(1, len(selected)))
    stats: dict[str, Any] = {"profiles": covered}
    cache: dict[str, Company] = {}
    started = utcnow()
    error: str | None = None
    visits = None
    try:
        if skip:
            _log(skip)
        elif careful:
            if not manual:
                pacing.wait_to_start(_log)
            visits = pacing.begin(_log)
        for raw in ([] if skip else source.fetch(ctx)):
            if cancel.requested():
                stats["cancelled"] = 1
                _log("stopped by user")
                break
            stats["fetched"] = stats.get("fetched", 0) + 1
            try:
                ingest_raw(db, raw, source.priority, priorities, stats, cache)
                if stats["fetched"] % 25 == 0:
                    run.log = "\n".join(lines)[-30000:]
                db.commit()   # short transactions: the CLI and the server share this SQLite file
            except Exception as e:  # keep going on a single bad record
                db.rollback()
                cache.clear()
                stats["errors"] = stats.get("errors", 0) + 1
                _log(f"  ! ingest error for {raw.title!r}: {e}")
        run.log = "\n".join(lines)[-30000:]
        db.commit()
        if source.kind == "ats" and not stats.get("cancelled"):   # a partial crawl must never drive expiry
            _expire_missing(db, name, companies, started, stats, ctx.truncated_company_ids)
    except Exception as e:
        db.rollback()
        error = f"{type(e).__name__}: {e}"
        _log("! " + error)
        _log(traceback.format_exc()[-1500:])
    finally:
        pacing.end()
    if visits and visits.refused:
        ctx.bump("blocked")
        _log(f"the site refused a visit ({visits.refused}): stopped reading it for now")
    stats.update({k: v for k, v in ctx.stats.items()})
    run.finished_at = utcnow()
    run.stats = stats
    run.error = error
    run.log = "\n".join(lines)[-30000:]
    if error:
        run.status = "error" if not stats.get("fetched") else "partial"
    elif any(stats.get(k) for k in ("company_errors", "blocked", "throttled", "login_required", "truncated", "cancelled")):
        run.status = "partial"
    else:
        run.status = "ok"
    db.commit()
    return run


def _expire_missing(db: Session, source_name: str, companies: list[Company], started: datetime, stats: dict,
                    truncated: set[int]) -> None:
    """An ATS board is a complete listing: jobs of a fully crawled company that were not seen this run are closed."""
    ok_ids = [c.id for c in companies
              if c.id not in truncated and c.last_crawled_at and c.last_crawled_at >= started - timedelta(seconds=5)]
    if not ok_ids:
        return
    rows = db.scalars(select(Job).where(Job.source == source_name, Job.company_id.in_(ok_ids),
                                        Job.last_seen_at < started,
                                        Job.status.notin_([JobStatus.APPLYING, JobStatus.APPLIED, JobStatus.EXPIRED,
                                                           JobStatus.REJECTED]))).all()
    if not rows:
        return
    for j in rows:
        j.expired_from, j.status = j.status, JobStatus.EXPIRED
    stats["expired"] = len(rows)
    # A twin on another source may still be live: make it the visible row instead of leaving it parked.
    prios = {n: c.priority for n, c in all_sources().items()}
    survivors = db.scalars(select(Job).where(Job.duplicate_of.in_([j.id for j in rows]),
                                             Job.status != JobStatus.EXPIRED)).all()
    by_parent: dict[int, list[Job]] = {}
    for s in survivors:
        by_parent.setdefault(s.duplicate_of, []).append(s)
    for parent_id, group in by_parent.items():
        group.sort(key=lambda s: (prios.get(s.source, 2), -(s.last_seen_at.timestamp() if s.last_seen_at else 0)))
        best = group[0]
        _unpark(best)
        for s in group[1:]:
            s.duplicate_of = best.id
        parent = db.get(Job, parent_id)
        if parent:
            parent.duplicate_of = best.id
    db.commit()


def crawl_all(db: Session, only: list[str] | None = None, log: Callable[[str], None] | None = None,
              profile_ids: list[int] | None = None, skip_kinds: tuple[str, ...] = ()) -> list[Run]:
    enabled = enabled_sources(db)
    names = only or [n for n, on in enabled.items() if on]
    names = [n for n in names if n not in all_sources() or all_sources()[n].kind not in skip_kinds]
    # cheap API sources first, browser ones last
    order = {"ats": 0, "board": 1, "browser": 2}
    sources = all_sources()
    names.sort(key=lambda n: order.get(sources[n].kind, 3) if n in sources else 9)
    runs = []
    for n in names:
        if cancel.requested():
            if log:
                log("stopped: remaining sources skipped")
            break
        if n not in sources:
            if log:
                log(f"skip unknown source {n}")
            continue
        if log:
            log(f"=== {n} ===")
        runs.append(run_source(n, db, log, manual=bool(only), profile_ids=profile_ids))
    return runs


_STALE_STATUSES = (JobStatus.NEW, JobStatus.QUEUED, JobStatus.SCORED, JobStatus.SHORTLISTED, JobStatus.FILTERED_OUT)


def expire_stale(db: Session, days: int | None = None) -> int:
    """Board and site postings carry no 'closed' signal: expire those no crawl has seen for `days` days.

    Company ATS boards expire precisely in _expire_missing; a job with an application is never touched, and a job that
    shows up again later is revived by ingest_raw.
    """
    from ..settings_store import get_setting

    days = days or int(get_setting(db, "jobs.stale_after_days") or 21)
    ats = [n for n, cls in all_sources().items() if cls.kind == "ats"]
    cutoff = utcnow() - timedelta(days=days)
    rows = db.scalars(select(Job).where(Job.source.notin_(ats), Job.last_seen_at < cutoff,
                                        Job.status.in_(_STALE_STATUSES))).all()
    n = 0
    for job in rows:
        if any(a.status != "withdrawn" for a in job.applications):
            continue
        job.expired_from, job.status = job.status, JobStatus.EXPIRED
        n += 1
    db.commit()
    return n
