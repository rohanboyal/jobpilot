"""AI fit scoring + genuineness (trust) scoring."""

from __future__ import annotations

import re
from collections.abc import Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import cancel
from ..config import SearchProfile
from ..llm.client import LLMBudgetExceeded, LLMError, run_llm
from ..llm.prompts import SCORE_SCHEMA, SCORE_SYSTEM, build_score_prompt
from ..models import Job, JobStatus, utcnow
from ..profiles import matches_any, pick_profile
from ..settings_store import get_setting
from ..sources.ats_detect import detect_ats
from .profile import profile_text, resume_for_profile

_SCAM = [
    (re.compile(r"registration fee|training fee|processing fee|security deposit|refundable deposit", re.I), "asks for a fee"),
    (re.compile(r"\bwhatsapp\b|\btelegram\b", re.I), "contact via WhatsApp/Telegram"),
    (re.compile(r"earn\s*(?:₹|rs\.?|\$|inr|usd)?\s*\d[\d,]{3,}.{0,25}(?:daily|per day|weekly|per week)", re.I), "unrealistic earnings claim"),
    (re.compile(r"no experience (?:needed|required).{0,60}(?:earn|income)", re.I), "no-experience + income pitch"),
    (re.compile(r"data entry|form filling|copy paste job|typing job", re.I), "data-entry style ad"),
    (re.compile(r"wire transfer|gift card|western union|crypto wallet", re.I), "payment-channel red flag"),
    (re.compile(r"mlm|multi[- ]level|network marketing|direct selling", re.I), "MLM wording"),
    (re.compile(r"\b(?:gmail|yahoo|hotmail|outlook|rediffmail)\.com\b", re.I), "free-mail contact address"),
]
_FREEMAIL_OK_SOURCES = {"hn_hiring"}
_CONFIDENTIAL = re.compile(r"confidential|client of|leading mnc|reputed company|hiring for a client", re.I)


def heuristic_trust(job: Job) -> tuple[int, list[str]]:
    flags: list[str] = []
    score = 65
    desc = job.description or ""
    src = job.source
    company = job.company
    if src in ("greenhouse", "lever", "ashby", "workable", "smartrecruiters", "company_careers"):
        score += 20
    elif detect_ats(job.apply_url):
        score += 15
        flags.append("applies through a company ATS")
    if company and (company.website or company.ats_slug):
        score += 10
    if not job.company_name or _CONFIDENTIAL.search(job.company_name or ""):
        score -= 15
        flags.append("employer not named")
    if desc and len(desc) < 150:
        score -= 10
        flags.append("very short description")
    for pat, label in _SCAM:
        if label == "free-mail contact address" and src in _FREEMAIL_OK_SOURCES:
            continue
        if pat.search(desc) or pat.search(job.title or ""):
            score -= 20
            flags.append(label)
    if (job.title or "").isupper() and len(job.title or "") > 12:
        score -= 5
        flags.append("shouty title")
    if src == "linkedin" and job.raw and not job.raw.get("apply_external"):
        score -= 5
    return max(0, min(100, score)), flags


def _job_dict(job: Job) -> dict:
    return {
        "source": job.source, "company_name": job.company_name, "title": job.title, "location": job.location,
        "remote": job.remote, "posted_at": job.posted_at.isoformat() if job.posted_at else None, "url": job.url,
        "salary_text": job.salary_text, "description": job.description,
    }


def score_job(db: Session, job: Job, search: SearchProfile | None = None, resume: str | None = None) -> dict:
    """search/resume: the profile and resume text to judge by (default: the job's best-matching profile and its resume)."""
    if search is None or resume is None:
        pid, picked = pick_profile(db, job.profile_ids)
        search = search or picked
        if resume is None:
            r = resume_for_profile(db, pid)
            resume = profile_text(db, r.id if r else None)
    result = run_llm(build_score_prompt(resume, search, _job_dict(job)), purpose="score",
                        schema=SCORE_SCHEMA, system=SCORE_SYSTEM, db=db)
    h_score, h_flags = heuristic_trust(job)
    legit = int(result.get("legit_confidence", 70))
    trust = round(0.5 * h_score + 0.5 * legit)
    flags = list(dict.fromkeys(h_flags + [f for f in result.get("red_flags", []) if f]))
    job.fit_score = int(result.get("fit_score", 0))
    job.fit = result
    job.scored_at = utcnow()
    job.trust_score = max(0, min(100, trust))
    job.trust_flags = flags
    job.tags = result.get("tags") or job.tags
    min_trust = int(get_setting(db, "pipeline.min_trust_for_shortlist", 40))
    # The AI call takes a while: read the status again, the user may have acted on the job in the meantime.
    current = db.scalar(select(Job.status).where(Job.id == job.id)) or job.status
    if current in (JobStatus.APPLYING, JobStatus.APPLIED, JobStatus.REJECTED):
        job.status = current                   # an application under way and "not interested" are never overridden
    elif job.fit_score >= search.min_fit_score and job.trust_score >= min_trust and result.get("verdict") != "skip":
        job.status = JobStatus.SHORTLISTED
    else:
        job.status = JobStatus.SCORED
    db.commit()
    return result


def _score_rows(db: Session, rows: list[Job], log: Callable[[str], None] | None, queued_only: bool = False,
                among: list[int] | None = None) -> dict:
    """among: the profiles of this run; a job is judged by the first of them it matched, with that profile's resume."""
    texts: dict[int | None, str] = {}
    stats = {"scored": 0, "shortlisted": 0, "errors": 0, "remaining": 0, "stopped": ""}
    for job in rows:
        if cancel.requested():
            stats["stopped"] = "stopped by user"
            break
        if queued_only and db.scalar(select(Job.status).where(Job.id == job.id)) != JobStatus.QUEUED:
            continue                            # changed since the run started (skipped, applied to, …)
        try:
            pid, search = pick_profile(db, job.profile_ids, among)
            r = resume_for_profile(db, pid)
            key = r.id if r else None
            if key not in texts:
                texts[key] = profile_text(db, key)
            score_job(db, job, search, texts[key])
            stats["scored"] += 1
            if job.status == JobStatus.SHORTLISTED:
                stats["shortlisted"] += 1
            if log:
                log(f"  {job.fit_score:>3}  {job.company_name} — {job.title}  ({job.status})")
        except LLMBudgetExceeded as e:
            stats["stopped"] = str(e)
            if log:
                log(f"stop: {e}")
            break
        except LLMError as e:
            stats["errors"] += 1
            db.rollback()
            if log:
                log(f"  ! {job.title}: {e}")
            if stats["errors"] >= 3:
                stats["stopped"] = "too many AI errors"
                break
    stats["remaining"] = db.scalar(select(func.count(Job.id)).where(Job.status == JobStatus.QUEUED)) or 0
    return stats


def score_queued(db: Session, limit: int | None = None, log: Callable[[str], None] | None = None,
                 profile_ids: list[int] | None = None) -> dict:
    """The Analyze stage: best new matches first (prefilter score, then newest), up to the per-run limit.
    profile_ids: only jobs matching one of these profiles (a run for some profiles)."""
    if limit is None:
        v = (get_setting(db, "schedule.analyze") or {}).get("limit")
        limit = 30 if v is None or v == "" else int(v)           # 0 is a real choice: score nothing this run
    if limit <= 0:
        return {"scored": 0, "shortlisted": 0, "errors": 0, "stopped": "",
                "remaining": db.scalar(select(func.count(Job.id)).where(Job.status == JobStatus.QUEUED)) or 0}
    stmt = select(Job).where(Job.status == JobStatus.QUEUED)
    if profile_ids is not None:
        stmt = stmt.where(matches_any(profile_ids))
    rows = db.scalars(
        stmt.order_by(Job.prefilter_score.desc().nullslast(), Job.posted_at.desc().nullslast(), Job.id.desc()).limit(limit)
    ).all()
    return _score_rows(db, list(rows), log, queued_only=True, among=profile_ids)


def score_jobs(db: Session, job_ids: list[int], log: Callable[[str], None] | None = None) -> dict:
    """Score the jobs the user picked, whatever their status (Analyze now on a selection)."""
    rows = [j for j in (db.get(Job, i) for i in job_ids) if j is not None]
    return _score_rows(db, rows, log)
