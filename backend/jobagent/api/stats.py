from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_session
from ..llm.client import budget_status
from ..models import Application, ApplicationStatus, Job, JobStatus, LlmCall, Run, utcnow
from ..schemas import JobOut, RunOut

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("")
def stats(db: Session = Depends(get_session)):
    now = utcnow()
    by_status = dict(db.execute(select(Job.status, func.count(Job.id)).where(Job.duplicate_of.is_(None)).group_by(Job.status)).all())
    by_source = dict(db.execute(select(Job.source, func.count(Job.id)).group_by(Job.source)).all())
    new_7d = db.scalar(select(func.count(Job.id)).where(Job.discovered_at >= now - timedelta(days=7), Job.duplicate_of.is_(None))) or 0
    apps_by_status = dict(db.execute(select(Application.status, func.count(Application.id)).group_by(Application.status)).all())
    outcomes = dict(db.execute(select(Application.outcome, func.count(Application.id))
                               .where(Application.status == ApplicationStatus.SUBMITTED).group_by(Application.outcome)).all())
    total = sum(by_status.values())
    passed = total - by_status.get(JobStatus.FILTERED_OUT, 0) - by_status.get(JobStatus.NEW, 0) - by_status.get(JobStatus.EXPIRED, 0)
    scored = sum(by_status.get(k, 0) for k in (JobStatus.SCORED, JobStatus.SHORTLISTED, JobStatus.REJECTED, JobStatus.APPLYING, JobStatus.APPLIED))
    shortlisted = sum(by_status.get(k, 0) for k in (JobStatus.SHORTLISTED, JobStatus.APPLYING, JobStatus.APPLIED))
    applied = by_status.get(JobStatus.APPLIED, 0)
    # Bucket by this Mac's calendar day (the DB holds UTC), so the bars agree with Today's "new today".
    offset = int((datetime.now().astimezone().utcoffset() or timedelta()).total_seconds() // 60)
    local_day = func.date(Job.discovered_at, f"{offset:+d} minutes")
    per_day = db.execute(
        select(local_day, func.count(Job.id)).where(Job.discovered_at >= now - timedelta(days=14))
        .group_by(local_day).order_by(local_day)).all()
    top = db.scalars(select(Job).where(Job.status.in_([JobStatus.SHORTLISTED, JobStatus.APPLYING]), Job.duplicate_of.is_(None))
                     .order_by(Job.fit_score.desc()).limit(8)).all()
    last_runs = db.scalars(select(Run).order_by(Run.started_at.desc()).limit(12)).all()
    llm_24h = db.execute(select(LlmCall.purpose, func.count(LlmCall.id)).where(LlmCall.created_at >= now - timedelta(hours=24))
                         .group_by(LlmCall.purpose)).all()
    return {
        "jobs": {"total": total, "new_7d": new_7d, "by_status": by_status, "by_source": by_source},
        "funnel": {"discovered": total, "passed_prefilter": max(passed, 0), "scored": scored, "shortlisted": shortlisted,
                   "applied": applied,
                   "heard_back": sum(outcomes.get(k, 0) for k in ("responded", "interview", "offer", "rejected")),
                   "interviews": sum(outcomes.get(k, 0) for k in ("interview", "offer")), "offers": outcomes.get("offer", 0)},
        "applications": {"by_status": apps_by_status,
                         "needs_review": apps_by_status.get(ApplicationStatus.NEEDS_REVIEW, 0),
                         "submitted": apps_by_status.get(ApplicationStatus.SUBMITTED, 0)},
        "discovered_per_day": [{"day": str(d), "count": c} for d, c in per_day],
        "top_shortlisted": [JobOut.model_validate(j).model_dump() for j in top],
        "last_runs": [RunOut.model_validate(r).model_dump() for r in last_runs],
        "budget": budget_status(db),
        "llm_24h": {p: c for p, c in llm_24h},
        "queued_for_scoring": by_status.get(JobStatus.QUEUED, 0),
    }
