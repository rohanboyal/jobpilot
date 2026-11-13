from __future__ import annotations

from datetime import UTC

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .. import tasks
from ..db import get_session
from ..models import Application, ApplicationStatus, JobStatus, Outcome, Profile, mark_submitted, utcnow
from ..pipeline.apply.runner import ApplicationLocked, apply_application, check_open
from ..schemas import ApplicationOut, ApplicationPatch, ApplicationWithJob, Page
from ..settings_store import get_setting

router = APIRouter(prefix="/applications", tags=["applications"])


@router.get("", response_model=Page)
def list_applications(db: Session = Depends(get_session), status: str | None = None, page: int = 1, page_size: int = 50):
    stmt = select(Application).options(selectinload(Application.job))
    if status:
        stmt = stmt.where(Application.status.in_([s.strip() for s in status.split(",") if s.strip()]))
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = db.scalars(stmt.order_by(Application.updated_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return Page(items=[ApplicationWithJob.model_validate(a) for a in rows], total=total, page=page, page_size=page_size)


@router.get("/{app_id}", response_model=ApplicationWithJob)
def get_application(app_id: int, db: Session = Depends(get_session)):
    a = db.get(Application, app_id, options=[selectinload(Application.job)])
    if not a:
        raise HTTPException(404, "application not found")
    return a


@router.patch("/{app_id}", response_model=ApplicationOut)
def patch_application(app_id: int, body: ApplicationPatch, db: Session = Depends(get_session)):
    a = db.get(Application, app_id)
    if not a:
        raise HTTPException(404, "application not found")
    if body.cover_letter is not None:
        a.cover_letter = body.cover_letter
    if body.answers is not None:
        a.answers = body.answers
    if body.resume_id is not None and body.resume_id != (a.resume_id or 1):
        _guard_not_sent(a)                       # what was sent is part of the record
        r = db.get(Profile, body.resume_id)
        if r is None or not r.resume_path:
            raise HTTPException(400, "that resume has no file")
        a.resume_id, a.resume_path = r.id, r.resume_path
    if body.clear_submit_click:
        if a.submitted_at is None or a.status not in (ApplicationStatus.NEEDS_REVIEW, ApplicationStatus.FAILED):
            raise HTTPException(409, "only an application whose submit outcome was unclear can be reset")
        a.submitted_at, a.confirmation, a.error = None, None, None
        a.log = ((a.log or "") + "\nyou confirmed the earlier submit did not go through").strip()
    if body.status is not None and body.status != a.status:
        if body.status not in ApplicationStatus.ALL:
            raise HTTPException(400, "invalid status")
        if a.status in (ApplicationStatus.SUBMITTED, ApplicationStatus.SUBMITTING):
            raise HTTPException(409, f"the application is already {a.status}; its status can't be changed back")
        a.status = body.status
        if body.status == ApplicationStatus.SUBMITTED:
            a.job.status = JobStatus.APPLIED
            a.confirmation = a.confirmation or "marked as submitted manually"
            a.submitted_at = a.submitted_at or utcnow()
            mark_submitted(a, int(get_setting(db, "applications.follow_up_days") or 10))
        if body.status == ApplicationStatus.WITHDRAWN and a.job.status == JobStatus.APPLYING:
            a.job.status = JobStatus.SHORTLISTED
    fields = body.model_fields_set
    if "outcome" in fields and body.outcome is not None:
        if body.outcome not in Outcome.ALL:
            raise HTTPException(400, f"outcome must be one of {Outcome.ALL}")
        if a.status != ApplicationStatus.SUBMITTED:
            raise HTTPException(409, "track the outcome after the application is submitted")
        if body.outcome != a.outcome:
            a.outcome, a.outcome_at = body.outcome, utcnow()
        if body.outcome not in Outcome.OPEN:
            a.follow_up_at = None
    if "outcome_notes" in fields:
        a.outcome_notes = body.outcome_notes
    if "follow_up_at" in fields:
        f = body.follow_up_at
        a.follow_up_at = f.astimezone(UTC).replace(tzinfo=None) if f is not None and f.tzinfo else f
    db.commit()
    return a


def _guard_not_sent(a: Application) -> None:
    """409 for applications that were sent, are being sent, were withdrawn, or whose submit was already clicked."""
    try:
        check_open(a)
    except ApplicationLocked as e:
        raise HTTPException(409, str(e)) from e


@router.post("/{app_id}/cover", response_model=ApplicationOut)
def write_cover(app_id: int, db: Session = Depends(get_session)):
    """Write the cover letter with the AI (one call). Only the letter changes: answers and status are kept."""
    from ..llm.client import LLMBudgetExceeded, LLMError
    from ..pipeline.prepare import write_cover_only

    a = db.get(Application, app_id)
    if not a:
        raise HTTPException(404, "application not found")
    _guard_not_sent(a)
    try:
        return write_cover_only(db, a)
    except LLMBudgetExceeded as e:
        raise HTTPException(409, str(e)) from e
    except LLMError as e:
        raise HTTPException(502, str(e)) from e


@router.post("/{app_id}/approve", response_model=ApplicationOut)
def approve(app_id: int, db: Session = Depends(get_session)):
    a = db.get(Application, app_id)
    if not a:
        raise HTTPException(404, "application not found")
    _guard_not_sent(a)
    a.status = ApplicationStatus.APPROVED
    db.commit()
    return a


@router.post("/{app_id}/fill")
def fill_only(app_id: int, db: Session = Depends(get_session)):
    """Open the form, fill it, take a screenshot, do not submit. Runs in the background."""
    a = db.get(Application, app_id)
    if not a:
        raise HTTPException(404, "application not found")
    _guard_not_sent(a)
    try:
        return tasks.start("apply", f"fill application #{app_id}",
                           lambda db2, log: apply_application(db2, app_id, submit=False, log=log).status)
    except tasks.TaskBusy as e:
        raise HTTPException(409, str(e)) from e


@router.post("/{app_id}/submit")
def submit(app_id: int, db: Session = Depends(get_session)):
    """Fill and submit. This is the one action that sends an application on your behalf."""
    a = db.get(Application, app_id)
    if not a:
        raise HTTPException(404, "application not found")
    _guard_not_sent(a)
    prev = a.status
    a.status = ApplicationStatus.APPROVED
    db.commit()
    try:
        return tasks.start("apply", f"submit application #{app_id}",
                           lambda db2, log: apply_application(db2, app_id, submit=True, log=log).status)
    except tasks.TaskBusy as e:
        a.status = prev
        db.commit()
        raise HTTPException(409, str(e)) from e


@router.get("/{app_id}/screenshot")
def screenshot(app_id: int, db: Session = Depends(get_session)):
    a = db.get(Application, app_id)
    if not a or not a.screenshot_path:
        raise HTTPException(404, "no screenshot yet")
    return FileResponse(a.screenshot_path, media_type="image/png")
