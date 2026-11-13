"""Everything the Today page shows in one request."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .. import scheduler
from ..config import load_answer_bank
from ..db import get_session
from ..llm.client import budget_status
from ..models import (
    Application,
    ApplicationStatus,
    Job,
    JobStatus,
    LlmCall,
    Outcome,
    Profile,
    Run,
    local_midnight_utc,
    utcnow,
)
from ..pipeline.prepare import _setting_int
from ..profiles import rows as profile_rows
from ..schemas import ApplicationWithJob, JobOut
from ..settings_store import get_setting
from .jobs import _to_out, count_jobs

_OPEN = f"{JobStatus.QUEUED},{JobStatus.SCORED},{JobStatus.SHORTLISTED}"

router = APIRouter(prefix="/today", tags=["today"])

_IMPORTANT_ANSWERS = ("full_name", "email", "phone", "current_location", "work_authorization",
                      "needs_visa_sponsorship", "notice_period", "years_of_experience")



@router.get("")
def today(db: Session = Depends(get_session)):
    now = utcnow()
    week = now - timedelta(days=7)
    midnight = local_midnight_utc()
    min_fit = _setting_int(get_setting(db, "schedule.prepare") or {}, "min_fit", 75)

    approvals = db.scalars(
        select(Application).options(selectinload(Application.job))
        .where(Application.status.in_([ApplicationStatus.NEEDS_REVIEW, ApplicationStatus.APPROVED]))
        .order_by(Application.updated_at.desc()).limit(20)
    ).all()
    approvals = sorted(approvals, key=lambda a: -(a.job.fit_score or 0))
    manual = db.scalar(select(func.count(Application.id)).where(Application.status == ApplicationStatus.MANUAL)) or 0

    strong = db.scalars(
        select(Job).options(selectinload(Job.applications))
        .where(Job.status == JobStatus.SHORTLISTED, Job.duplicate_of.is_(None))
        .order_by(Job.fit_score.desc(), Job.scored_at.desc()).limit(6)
    ).all()
    new_today = db.scalar(select(func.count(Job.id)).where(Job.discovered_at >= midnight, Job.duplicate_of.is_(None))) or 0
    # Same queries as the Jobs tabs these cards open, so the numbers match what the user lands on.
    matched_today = count_jobs(db, status=_OPEN, not_applied=True, found_today=True)
    queued = count_jobs(db, status=JobStatus.QUEUED, not_applied=True)
    last_collect = db.scalar(select(func.max(Run.finished_at)).where(Run.kind == "crawl"))
    last_analyze = db.scalar(select(func.max(Job.scored_at)))
    drafted = db.scalar(select(func.count(Application.id)).where(Application.created_at >= week,
                                                                 Application.cover_letter.is_not(None),
                                                                 Application.cover_letter != "")) or 0
    submitted_7d = db.scalar(select(func.count(Application.id)).where(Application.submitted_at >= week)) or 0
    collected_7d = db.scalar(select(func.count(Job.id)).where(Job.discovered_at >= week, Job.duplicate_of.is_(None))) or 0
    analyzed_7d = db.scalar(select(func.count(Job.id)).where(Job.scored_at >= week)) or 0
    ai_7d = db.scalar(select(func.count(LlmCall.id)).where(LlmCall.created_at >= week, LlmCall.ok.is_(True),
                                                          LlmCall.model.not_like("ollama:%"))) or 0

    follow = db.scalars(
        select(Application).options(selectinload(Application.job))
        .where(Application.status == ApplicationStatus.SUBMITTED, Application.follow_up_at.is_not(None),
               Application.follow_up_at <= now, Application.outcome.in_(Outcome.OPEN))
        .order_by(Application.follow_up_at).limit(10)
    ).all()
    outcomes = dict(db.execute(select(Application.outcome, func.count(Application.id))
                               .where(Application.status == ApplicationStatus.SUBMITTED).group_by(Application.outcome)).all())
    from ..health import attention_count
    from ..settings_store import enabled_sources
    from .profile import _stale

    attention = attention_count(db, [n for n, on in enabled_sources(db).items() if on])
    stale_resume = _stale(db)

    sched = scheduler.info()
    profile = db.get(Profile, 1)
    bank = load_answer_bank().flat()
    filled = [k for k in _IMPORTANT_ANSWERS if bank.get(k)]
    return {
        "approvals": [ApplicationWithJob.model_validate(a).model_dump() | {"job": _to_out(a.job).model_dump()}
                      for a in approvals],
        "manual_count": manual,
        "follow_ups": [ApplicationWithJob.model_validate(a).model_dump() | {"job": _to_out(a.job).model_dump()} for a in follow],
        "outcomes": {k or "awaiting": v for k, v in outcomes.items()},
        "sources_attention": attention,
        "stale_resume": {"jobs": len(stale_resume["job_ids"]), "drafts": len(stale_resume["app_ids"])},
        "strong_matches": [JobOut.model_validate(_to_out(j)).model_dump() for j in strong],
        "min_fit": min_fit,
        "stages": {
            "collect": {"new_today": new_today, "matched_today": matched_today, "last_run_at": last_collect.isoformat() if last_collect else None,
                        **{k: sched["stages"]["collect"].get(k) for k in ("enabled", "days", "time", "next_run_at")}},
            "analyze": {"waiting": queued, "last_run_at": last_analyze.isoformat() if last_analyze else None,
                        **{k: sched["stages"]["analyze"].get(k) for k in ("enabled", "days", "time", "limit", "next_run_at")}},
            "prepare": {"drafted_7d": drafted, **sched["prepare"]},
            "apply": {"mode": sched["apply_mode"], "submitted_7d": submitted_7d},
        },
        "paused": sched["paused"],
        "scheduler_available": sched["available"],
        "week": {"collected": collected_7d, "analyzed": analyzed_7d, "submitted": submitted_7d, "ai_calls": ai_7d},
        "budget": budget_status(db),
        "setup": {
            "completed": bool(get_setting(db, "setup.completed")),
            "has_resume": bool(profile and (profile.resume_text or "").strip())
            or bool(db.scalar(select(func.count(Profile.id)).where(Profile.resume_text.is_not(None), Profile.resume_text != ""))),
            "answers_filled": len(filled), "answers_needed": len(_IMPORTANT_ANSWERS),
            "profiles": len(profile_rows(db)),
        },
    }
