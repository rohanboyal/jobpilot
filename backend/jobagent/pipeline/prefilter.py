"""Cheap, deterministic gate so only plausible jobs spend AI quota."""

from __future__ import annotations

import re
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import SearchProfile
from ..models import Job, JobStatus, utcnow
from ..utils.jobinfo import annotate

# Words in a remote job's location that do not tie it to a place. Whatever is left after removing them names a
# country or city ("Remote - USA", "Dublin"), which means the role is open only there.
_LOC_FILLER = re.compile(
    r"\b(remote|hybrid|on-?site|wfh|work from home|from home|fully|full[- ]time|part[- ]time|flexible|first|friendly|"
    r"only|based|location|locations|multiple|various|any|the|or|and|in|of|within|n/?a|not specified|office|home|"
    r"utc|gmt|tz|time ?zones?|hours?|overlap)\b|[^a-z]+")
# Open everywhere, or a region broad enough that only the AI can tell whether the user's country is included.
_LOC_OPEN = re.compile(r"\b(anywhere|worldwide|world|global|globally|international|distributed|earth|apac|asia|"
                       r"asia[- ]pacific|emea|south asia|row)\b")


def _remote_elsewhere(loc: str) -> bool:
    """True when a remote job's location text names a specific place (it already failed the user's location list)."""
    if not loc or _LOC_OPEN.search(loc):
        return False
    return len(_LOC_FILLER.sub(" ", loc).strip()) >= 2


def prefilter_job(job: Job, search: SearchProfile) -> tuple[int, list[str], bool]:
    """Return (score 0-100, reasons, passed)."""
    reasons: list[str] = []
    score = 0
    title = (job.title or "").lower()
    loc = (job.location or "").lower()
    desc = (job.description or "").lower()

    if job.duplicate_of:
        return 0, [f"duplicate of #{job.duplicate_of}"], False

    for x in search.exclude_keywords:
        if x.strip() and x.lower() in title:
            return 0, [f"excluded keyword '{x.strip()}' in title"], False
    company = (job.company_name or "").lower()
    for x in search.exclude_companies:
        if x.strip() and x.strip().lower() in company:
            return 0, [f"company '{job.company_name}' is on your exclude list"], False
    if search.job_types and job.job_type and job.job_type not in search.job_types:
        return 0, [f"{job.job_type.replace('_', '-')} role, not one of your job types"], False

    kws = [k.lower() for k in search.title_keywords if k.strip()]
    if kws:
        hit = [k for k in kws if k in title]
        if hit:
            score += 40
            reasons.append(f"title matches '{hit[0]}'")
        else:
            return 0, ["title has none of your title keywords"], False
    else:
        score += 40

    if job.posted_at and search.max_age_days:
        age = utcnow() - job.posted_at
        if age > timedelta(days=search.max_age_days):
            return score, [f"posted {age.days} days ago (> {search.max_age_days})"], False

    locs = [x.lower() for x in search.locations if x.strip()]
    places = [x for x in locs if _LOC_FILLER.sub(" ", x).strip() and not _LOC_OPEN.search(x)]   # not "Remote"
    if not locs:
        score += 20
    elif any(x in loc for x in places):
        score += 20
        reasons.append("location matches")
    elif (job.remote or "remote" in loc) and search.remote_ok and _remote_elsewhere(loc):
        return score, [f"remote, but only in '{job.location}'"], False
    elif any(x in loc for x in locs):
        score += 20
        reasons.append("location matches")
    elif job.remote and search.remote_ok:
        score += 20
        reasons.append("remote")
    elif not loc:
        score += 10
        reasons.append("location unknown")
    elif "remote" in loc and search.remote_ok:
        score += 15
        reasons.append("remote (from location text)")
    else:
        return score, [f"location '{job.location}' not in your list and not remote"], False

    mode = job.work_mode
    if mode == "remote" and not search.remote_ok:
        return score, ["remote role, but you chose not to see remote jobs"], False
    if mode == "hybrid" and not search.hybrid_ok:
        return score, ["hybrid role, but you chose not to see hybrid jobs"], False
    if (mode == "onsite" or (mode is None and job.remote is False)) and not search.onsite_ok:
        return score, ["onsite role, but you chose not to see onsite jobs"], False

    if job.exp_min is not None and search.experience_max is not None and job.exp_min > search.experience_max:
        need = f"{job.exp_min:g}-{job.exp_max:g}" if job.exp_max is not None else f"{job.exp_min:g}+"
        return score, [f"asks for {need} years of experience (your limit is {search.experience_max:g})"], False
    if job.exp_max is not None and search.experience_min and job.exp_max < search.experience_min:
        return score, [f"for up to {job.exp_max:g} years of experience (below your minimum of {search.experience_min:g})"], False

    if job.salary_max:
        floor = search.min_salary_inr if job.salary_currency == "INR" else search.min_salary_usd if job.salary_currency == "USD" else None
        if floor and job.salary_max < floor:
            return score, [f"pays up to {job.salary_currency} {job.salary_max:,.0f} a year, below your minimum"], False

    if desc:
        bad = next((w for w in search.must_not_mention if w.strip() and w.strip().lower() in desc), None)
        if bad:
            return score, [f"description mentions '{bad.strip()}'"], False
        want = [w.strip().lower() for w in search.must_mention if w.strip()]
        if want and not any(w in desc for w in want):
            return score, ["description mentions none of your must-have words"], False

    skills = [s.lower() for s in search.skills if s.strip()]
    if desc and skills:
        found = [s for s in skills if s in desc]
        score += min(30, 6 * len(found))
        if found:
            reasons.append("skills: " + ", ".join(found[:6]))
    else:
        score += 10
        reasons.append("no description yet")

    if job.description and len(job.description) > 400:
        score += 10
    score = max(0, min(100, score))
    return score, reasons, score >= search.min_prefilter_score


def match_profiles(job: Job, profiles: list[tuple[int, SearchProfile]]) -> tuple[int, list[str], bool, list[int]]:
    """Check a job against every profile. Returns (best score, its reasons, passed any, matched profile ids best-first)."""
    if job.duplicate_of:
        return 0, [f"duplicate of #{job.duplicate_of}"], False, []
    passed: list[tuple[int, int, list[str]]] = []
    best: tuple[int, list[str]] | None = None
    for pid, sp in profiles:
        score, reasons, ok = prefilter_job(job, sp)
        if ok:
            passed.append((score, pid, reasons))
        elif best is None or score > best[0]:
            best = (score, reasons)
    if passed:
        passed.sort(key=lambda t: -t[0])
        return passed[0][0], passed[0][2], True, [pid for _, pid, _ in passed]
    score, reasons = best or (0, ["no search profile is enabled"])
    return score, reasons, False, []


def _profiles(db: Session, search: SearchProfile | None) -> list[tuple[int, SearchProfile]]:
    from ..profiles import enabled_profiles

    return [(0, search)] if search is not None else enabled_profiles(db)


def prefilter_new(db: Session, search: SearchProfile | None = None) -> dict[str, int]:
    profiles = _profiles(db, search)
    rows = db.scalars(select(Job).where(Job.status == JobStatus.NEW)).all()
    stats = {"checked": 0, "queued": 0, "filtered_out": 0}
    for job in rows:
        annotate(job)
        score, reasons, ok, ids = match_profiles(job, profiles)
        job.prefilter_score = score
        job.prefilter_reasons = reasons
        job.profile_ids = ids or None
        job.status = JobStatus.QUEUED if ok else JobStatus.FILTERED_OUT
        stats["checked"] += 1
        stats["queued" if ok else "filtered_out"] += 1
    db.commit()
    return stats


_REMATCH = (JobStatus.QUEUED, JobStatus.FILTERED_OUT)


def rematch(db: Session) -> dict[str, int]:
    """Profiles changed: re-run the free prefilter on every job that has not been scored or acted on yet.

    Duplicate-parked rows stay parked; scored, shortlisted, applied and expired jobs keep their state but get their
    profile tags refreshed so filters by profile stay right.
    """
    profiles = _profiles(db, None)
    stats = {"checked": 0, "queued": 0, "filtered_out": 0, "retagged": 0}
    for job in db.scalars(select(Job).where(Job.duplicate_of.is_(None))).all():
        annotate(job)
        score, reasons, ok, ids = match_profiles(job, profiles)
        if job.status in _REMATCH:
            job.prefilter_score, job.prefilter_reasons = score, reasons
            job.status = JobStatus.QUEUED if ok else JobStatus.FILTERED_OUT
            stats["checked"] += 1
            stats["queued" if ok else "filtered_out"] += 1
        else:
            stats["retagged"] += 1
        job.profile_ids = ids or None
    db.commit()
    return stats


def requeue_filtered(db: Session, job_id: int) -> Job | None:
    job = db.get(Job, job_id)
    if job and job.status in (JobStatus.FILTERED_OUT, JobStatus.EXPIRED):
        job.status = JobStatus.QUEUED
        db.commit()
    return job
