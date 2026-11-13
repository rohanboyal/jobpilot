"""Draft a cover letter and gather answers for a shortlisted job → Application (needs_review / manual)."""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from .. import cancel
from ..config import load_answer_bank
from ..llm.client import LLMBudgetExceeded, LLMError, run_llm
from ..llm.prompts import COVER_SCHEMA, COVER_SYSTEM, build_cover_prompt
from ..models import Application, ApplicationStatus, Job, JobStatus, Profile, utcnow
from ..profiles import matches_any
from ..settings_store import get_setting
from ..sources.ats_detect import detect_ats
from .profile import profile_text, resume_for_job

_MANUAL_SOURCES = {"hn_hiring", "dice"}   # Dice's API terms allow discovery only; the user applies on dice.com


_ATS_SOURCES = {"greenhouse", "lever", "ashby", "workable", "smartrecruiters"}


def is_manual_source(job: Job) -> bool:
    return (job.source in _MANUAL_SOURCES
            or (job.source == "linkedin" and not (job.raw or {}).get("apply_external"))   # login-walled page
            or "linkedin.com/" in (job.apply_url or "")      # any source whose apply link is a LinkedIn page
            or not (job.apply_url or job.url))


def apply_method(job: Job) -> str:
    """'autofill' (a known ATS form JobPilot can fill) | 'site' (opens the job site; may need a login) | 'manual'."""
    if is_manual_source(job):
        return "manual"
    if job.source in _ATS_SOURCES or detect_ats(job.apply_url or job.url):
        return "autofill"
    return "site"


def _open_application(job: Job) -> Application | None:
    for a in job.applications:
        if a.status not in (ApplicationStatus.WITHDRAWN, ApplicationStatus.FAILED):
            return a
    return None


def _setting_int(cfg: dict, key: str, default: int) -> int:
    """0 is a real choice ("no cover letters per run"), so only a missing value falls back to the default."""
    v = cfg.get(key)
    return default if v is None or v == "" else int(v)


def wants_cover(db: Session, job: Job, cover: str) -> bool:
    """'always' | 'never' | 'auto' (only for top matches: fit at or above the prepare threshold)."""
    if cover in ("always", "never"):
        return cover == "always"
    min_fit = _setting_int(get_setting(db, "schedule.prepare") or {}, "min_fit", 75)
    return job.fit_score is not None and job.fit_score >= min_fit


class AlreadySent(ValueError):
    """The job's application was sent or is being sent; preparing it again would undo that."""


def draft_cover(db: Session, job: Job, resume_id: int | None = None) -> dict:
    """One AI call: {'cover_letter', 'short_pitch'} for this job from that resume. Raises LLMError."""
    return run_llm(build_cover_prompt(profile_text(db, resume_id), {
        "company_name": job.company_name, "title": job.title, "location": job.location, "description": job.description,
    }, job.fit), purpose="cover", schema=COVER_SCHEMA, system=COVER_SYSTEM, db=db)


def write_cover_only(db: Session, app: Application) -> Application:
    """Write (or rewrite) just the cover letter of an open application. Answers and status stay as they are."""
    result = draft_cover(db, app.job, app.resume_id)
    letter = (result.get("cover_letter") or "").strip()
    if not letter:
        raise LLMError("the AI returned no cover letter")
    app.cover_letter = letter
    app.drafted_at = utcnow()
    app.log = ((app.log or "") + "\ncover letter written on request").strip()
    db.commit()
    db.refresh(app)
    return app


def prepare_application(db: Session, job_id: int, force: bool = False, cover: str = "auto",
                        resume_id: int | None = None, among: list[int] | None = None) -> Application:
    """resume_id: the resume to use (default: the one already chosen for this application, else the resume of the
    profile the job matched, of `among` when a run covers only some profiles)."""
    job = db.get(Job, job_id)
    if job is None:
        raise ValueError(f"job {job_id} not found")
    existing = _open_application(job)
    if existing and (existing.status in (ApplicationStatus.SUBMITTING, ApplicationStatus.SUBMITTED)
                     or existing.submitted_at is not None):
        if not force:
            return existing
        raise AlreadySent("this application was already sent (or its submit was clicked); it can't be prepared again")
    if existing and not force:
        if job.status not in (JobStatus.APPLYING, JobStatus.APPLIED):
            job.status = JobStatus.APPLYING          # an open application always means the job is under way
            db.commit()
        return existing

    resume = db.get(Profile, resume_id or (existing.resume_id if existing else None) or 0) or resume_for_job(db, job, among)
    result: dict = {"cover_letter": "", "short_pitch": ""}
    if wants_cover(db, job, cover):
        try:
            result = draft_cover(db, job, resume.id if resume else None)
        except LLMBudgetExceeded:
            raise
        except LLMError as e:
            result = {"cover_letter": "", "short_pitch": "", "error": str(e)}

    bank = load_answer_bank()
    answers = bank.flat()
    # Re-preparing refreshes the answer-bank keys but keeps what the user typed for this application.
    if existing:
        answers = {**{k: v for k, v in (existing.answers or {}).items() if k not in answers}, **answers}
        if "why_this_role" in (existing.answers or {}) and not result.get("short_pitch"):
            answers["why_this_role"] = existing.answers["why_this_role"]
    if result.get("short_pitch"):
        answers["why_this_role"] = result["short_pitch"]
    ats = detect_ats(job.apply_url or job.url)
    ats_type = ats[0] if ats else (job.company.ats_type if job.company and job.company.ats_type not in ("unknown", "custom") else None)
    manual = get_setting(db, "apply.mode") == "manual" or is_manual_source(job)   # the user applies by hand

    app = existing or Application(job_id=job.id)
    app.status = ApplicationStatus.MANUAL if manual else ApplicationStatus.NEEDS_REVIEW
    app.method = "manual" if manual else "browser"
    app.ats_type = ats_type
    new_letter = result.get("cover_letter") or ""
    app.cover_letter = new_letter or app.cover_letter
    cover_state = "new" if new_letter else "kept" if app.cover_letter else "none"
    app.answers = answers
    app.resume_id = resume.id if resume else None
    app.resume_path = resume.resume_path if resume else None
    app.drafted_at = utcnow()
    app.log = ((app.log or "") + f"\nprepared (ats={ats_type or 'generic'}, manual={manual}, "
               f"cover={cover_state})").strip()
    if result.get("error"):
        app.log += f"\ncover letter failed: {result['error']}"
    db.add(app)
    job.status = JobStatus.APPLYING
    db.commit()
    db.refresh(app)
    app.cover_state = cover_state       # not stored: tells the caller whether this run wrote the letter
    return app


def prepare_shortlisted(db: Session, limit: int | None = None, log: Callable[[str], None] | None = None,
                        profile_ids: list[int] | None = None) -> dict:
    """The Prepare stage: shortlisted jobs at or above the prepare threshold, highest fit first.
    profile_ids: only jobs matching one of these profiles (a run for some profiles)."""
    cfg = get_setting(db, "schedule.prepare") or {}
    limit = limit if limit is not None else _setting_int(cfg, "limit", 6)
    min_fit = _setting_int(cfg, "min_fit", 75)
    if limit <= 0:
        return {"prepared": 0, "errors": 0, "stopped": ""}
    # A job that already has an application, even a withdrawn one, is never drafted again automatically.
    stmt = select(Job).where(Job.status == JobStatus.SHORTLISTED, Job.fit_score >= min_fit,
                             ~exists().where(Application.job_id == Job.id))
    if profile_ids is not None:
        stmt = stmt.where(matches_any(profile_ids))
    rows = db.scalars(stmt.order_by(Job.fit_score.desc(), Job.id.desc()).limit(limit)).all()
    stats = {"prepared": 0, "errors": 0, "stopped": ""}
    for job in rows:
        if cancel.requested():
            stats["stopped"] = "stopped by user"
            break
        try:
            app = prepare_application(db, job.id, among=profile_ids)
            stats["prepared"] += 1
            if log:
                log(f"  prepared #{app.id} for {job.company_name} — {job.title} ({app.status})")
        except LLMBudgetExceeded as e:
            stats["stopped"] = str(e)
            break
        except Exception as e:
            stats["errors"] += 1
            db.rollback()
            if log:
                log(f"  ! {job.title}: {e}")
    return stats
