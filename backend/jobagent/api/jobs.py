from __future__ import annotations

from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import Select, exists, func, or_, select, text
from sqlalchemy.orm import Session, selectinload

from .. import tasks
from ..db import get_session
from ..models import Application, ApplicationStatus, Job, JobStatus, local_midnight_utc, utcnow
from ..pipeline.prefilter import requeue_filtered
from ..pipeline.prepare import AlreadySent, apply_method, prepare_application
from ..pipeline.profile import profile_text
from ..pipeline.scoring import score_job
from ..schemas import ApplicationOut, JobDetail, JobOut, JobPatch, Page, StatusChange
from ..settings_store import get_setting
from ..sources.base import all_sources

router = APIRouter(prefix="/jobs", tags=["jobs"])

_SORTS = {
    "fit": (Job.fit_score.desc().nullslast(), Job.discovered_at.desc()),
    "newest": (Job.discovered_at.desc(),),
    "posted": (Job.posted_at.desc().nullslast(),),
    "prefilter": (Job.prefilter_score.desc().nullslast(),),
    "trust": (Job.trust_score.desc().nullslast(),),
}
_ATS_HOSTS = ("greenhouse.io", "lever.co", "ashbyhq.com", "workable.com", "smartrecruiters.com")
_ATS_SOURCES = ("greenhouse", "lever", "ashby", "workable", "smartrecruiters")


def _to_out(job: Job) -> JobOut:
    out = JobOut.model_validate(job)
    out.has_description = bool(job.description)
    out.apply_method = apply_method(job)
    open_app = next((a for a in job.applications if a.status != ApplicationStatus.WITHDRAWN), None)
    if open_app:
        out.application_id, out.application_status = open_app.id, open_app.status
        out.application_outcome = open_app.outcome
    return out


def _csv(v: str | None) -> list[str]:
    return [s.strip() for s in (v or "").split(",") if s.strip()]


def job_query(
    *, status: str | None = None, source: str | None = None, source_kind: str | None = None, q: str | None = None,
    where: str | None = None, min_fit: int | None = None, unscored: bool | None = None, min_trust: int | None = None,
    remote: bool | None = None, autofill: bool | None = None, not_applied: bool = False, in_progress: bool = False,
    applied: bool = False, posted_within_days: int | None = None, found_today: bool = False,
    found_within_days: int | None = None, profile_id: int | None = None, max_experience: float | None = None,
    work_mode: str | None = None, job_type: str | None = None, min_salary_inr: float | None = None,
    salary_shown: bool = False, include_unstated: bool = True, company_id: int | None = None,
    include_duplicates: bool = False, keep_days: int | None = None,
) -> Select:
    """The Jobs list filters as one query, shared with the Today page so its numbers match the lists they open."""
    stmt = select(Job)
    if keep_days:      # found longer ago: out of the lists, unless the user applied or has an application under way
        stmt = stmt.where(or_(Job.discovered_at >= utcnow() - timedelta(days=keep_days),
                              Job.status.in_([JobStatus.APPLYING, JobStatus.APPLIED]),
                              exists().where(Application.job_id == Job.id)))
    if status:
        stmt = stmt.where(Job.status.in_(_csv(status)))
    if source:
        stmt = stmt.where(Job.source.in_(_csv(source)))
    if source_kind:
        kinds = set(_csv(source_kind))
        names = [n for n, c in all_sources().items() if c.kind in kinds]
        stmt = stmt.where(Job.source.in_(names))
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Job.title.ilike(like), Job.company_name.ilike(like), Job.location.ilike(like)))
    if where:
        stmt = stmt.where(Job.location.ilike(f"%{where.strip()}%"))
    if unscored is True:
        stmt = stmt.where(Job.fit_score.is_(None))
    elif unscored is False:
        stmt = stmt.where(Job.fit_score.is_not(None))
    if min_fit is not None:
        stmt = stmt.where(Job.fit_score >= min_fit)
    if min_trust is not None:
        stmt = stmt.where(Job.trust_score >= min_trust)
    if remote is not None:
        stmt = stmt.where(Job.remote.is_(remote))
    if autofill:
        stmt = stmt.where(or_(Job.source.in_(_ATS_SOURCES), *[Job.apply_url.ilike(f"%{h}%") for h in _ATS_HOSTS]))
    sent = exists().where(Application.job_id == Job.id, Application.submitted_at.is_not(None))
    open_app = exists().where(Application.job_id == Job.id, Application.submitted_at.is_(None),
                              Application.status.notin_([ApplicationStatus.SUBMITTED, ApplicationStatus.WITHDRAWN]))
    if not_applied:
        stmt = stmt.where(Job.status.notin_([JobStatus.APPLYING, JobStatus.APPLIED]), ~sent, ~open_app)
    if in_progress:
        stmt = stmt.where(open_app, ~sent)
    if applied:
        stmt = stmt.where(or_(Job.status == JobStatus.APPLIED, sent))
    if posted_within_days:
        since = utcnow() - timedelta(days=posted_within_days)
        stmt = stmt.where(or_(Job.posted_at >= since, Job.posted_at.is_(None) & (Job.discovered_at >= since)))
    if found_today:
        stmt = stmt.where(Job.discovered_at >= local_midnight_utc())
    elif found_within_days:
        stmt = stmt.where(Job.discovered_at >= utcnow() - timedelta(days=found_within_days))
    if profile_id:
        stmt = stmt.where(text("EXISTS (SELECT 1 FROM json_each(jobs.profile_ids) WHERE json_each.value = :pid)")
                          .bindparams(pid=profile_id))

    def stated(col, cond):
        return or_(col.is_(None), cond) if include_unstated else cond

    if max_experience is not None:
        stmt = stmt.where(stated(Job.exp_min, Job.exp_min <= max_experience))
    if work_mode:
        stmt = stmt.where(stated(Job.work_mode, Job.work_mode.in_(_csv(work_mode))))
    if job_type:
        stmt = stmt.where(stated(Job.job_type, Job.job_type.in_(_csv(job_type))))
    if min_salary_inr:
        # Other currencies are not converted, so they are kept rather than guessed.
        stmt = stmt.where(stated(Job.salary_max, or_(Job.salary_currency != "INR", Job.salary_max >= min_salary_inr)))
    if salary_shown:
        stmt = stmt.where(Job.salary_max.is_not(None))
    if company_id:
        stmt = stmt.where(Job.company_id == company_id)
    if not include_duplicates:
        stmt = stmt.where(Job.duplicate_of.is_(None))
    return stmt


def keep_days(db: Session) -> int:
    """How long a found job stays in the lists (0 = forever)."""
    try:
        return max(0, int(get_setting(db, "jobs.keep_days") or 0))
    except (TypeError, ValueError):
        return 30


def count_jobs(db: Session, **filters) -> int:
    filters.setdefault("keep_days", keep_days(db))
    return db.scalar(select(func.count()).select_from(job_query(**filters).subquery())) or 0


@router.get("", response_model=Page)
def list_jobs(
    db: Session = Depends(get_session),
    status: str | None = Query(None, description="comma list of statuses"),
    source: str | None = None,
    source_kind: str | None = Query(None, description="ats | board | browser (comma list)"),
    q: str | None = None,
    where: str | None = Query(None, description="substring of the location"),
    min_fit: int | None = None,
    unscored: bool | None = Query(None, description="true = only jobs not analyzed yet; false = only analyzed"),
    min_trust: int | None = None,
    remote: bool | None = None,
    autofill: bool | None = Query(None, description="only jobs whose form JobPilot can fill"),
    not_applied: bool = False,
    in_progress: bool = Query(False, description="only jobs with an application being prepared, reviewed or sent by hand"),
    applied: bool = Query(False, description="only jobs you applied to"),
    posted_within_days: int | None = None,
    found_today: bool = Query(False, description="only jobs JobPilot found since local midnight"),
    found_within_days: int | None = None,
    profile_id: int | None = None,
    max_experience: float | None = Query(None, description="hide jobs that ask for more years than this"),
    work_mode: str | None = Query(None, description="remote | hybrid | onsite (comma list)"),
    job_type: str | None = Query(None, description="full_time | part_time | contract | internship | freelance (comma list)"),
    min_salary_inr: float | None = Query(None, description="annual INR; jobs that state less are hidden"),
    salary_shown: bool = False,
    include_unstated: bool = Query(True, description="experience/mode/type/salary filters also keep jobs that don't say"),
    company_id: int | None = None,
    include_duplicates: bool = False,
    sort: str = "fit",
    page: int = 1,
    page_size: int = 50,
):
    stmt = job_query(
        keep_days=keep_days(db),
        status=status, source=source, source_kind=source_kind, q=q, where=where, min_fit=min_fit, unscored=unscored,
        min_trust=min_trust, remote=remote, autofill=autofill, not_applied=not_applied, in_progress=in_progress,
        applied=applied, posted_within_days=posted_within_days, found_today=found_today,
        found_within_days=found_within_days, profile_id=profile_id, max_experience=max_experience, work_mode=work_mode,
        job_type=job_type, min_salary_inr=min_salary_inr, salary_shown=salary_shown, include_unstated=include_unstated,
        company_id=company_id, include_duplicates=include_duplicates,
    )
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    stmt = (stmt.options(selectinload(Job.applications)).order_by(*_SORTS.get(sort, _SORTS["fit"]))
            .offset((page - 1) * page_size).limit(page_size))
    items = [_to_out(j) for j in db.scalars(stmt).all()]
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/sources")
def job_sources(status: str | None = None, include_duplicates: bool = False, db: Session = Depends(get_session)):
    """Sources that have jobs in these statuses, with counts, for the Jobs page source filter."""
    stmt = select(Job.source, func.count()).group_by(Job.source)
    if status:
        stmt = stmt.where(Job.status.in_(_csv(status)))
    if not include_duplicates:
        stmt = stmt.where(Job.duplicate_of.is_(None))
    reg = all_sources()
    rows = [{"source": s, "label": reg[s].label if s in reg else s, "kind": reg[s].kind if s in reg else "browser", "count": n}
            for s, n in db.execute(stmt).all()]
    return sorted(rows, key=lambda r: (-r["count"], r["label"].lower()))


@router.get("/{job_id}", response_model=JobDetail)
def get_job(job_id: int, db: Session = Depends(get_session)):
    job = db.get(Job, job_id, options=[selectinload(Job.applications), selectinload(Job.company)])
    if not job:
        raise HTTPException(404, "job not found")
    out = JobDetail.model_validate(job)
    out.has_description = bool(job.description)
    out.apply_method = apply_method(job)
    open_app = next((a for a in job.applications if a.status != ApplicationStatus.WITHDRAWN), None)
    if open_app:
        out.application_id, out.application_status = open_app.id, open_app.status
        out.application_outcome = open_app.outcome
    return out


@router.patch("/{job_id}", response_model=JobOut)
def patch_job(job_id: int, body: JobPatch, db: Session = Depends(get_session)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "job not found")
    if body.notes is not None:
        job.notes = body.notes
    if body.tags is not None:
        job.tags = body.tags
    db.commit()
    return _to_out(job)


class StatusLocked(ValueError):
    """The job has an application under way or sent; only "not interested" may change it."""


def _set_status(db: Session, job: Job, status: str) -> None:
    has_app = any(a.status != ApplicationStatus.WITHDRAWN for a in job.applications)
    if (job.status in (JobStatus.APPLYING, JobStatus.APPLIED) or has_app) and status != JobStatus.REJECTED:
        raise StatusLocked("this job has an application; open it under Applications instead")
    if status == JobStatus.QUEUED:
        requeue_filtered(db, job.id)
    job.status = status
    if status == JobStatus.REJECTED:
        for a in job.applications:
            if a.status in (ApplicationStatus.DRAFT, ApplicationStatus.NEEDS_REVIEW, ApplicationStatus.APPROVED):
                a.status = ApplicationStatus.WITHDRAWN


@router.post("/{job_id}/status", response_model=JobOut)
def set_status(job_id: int, body: StatusChange, db: Session = Depends(get_session)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "job not found")
    if body.status not in JobStatus.ALL:
        raise HTTPException(400, f"invalid status; one of {JobStatus.ALL}")
    try:
        _set_status(db, job, body.status)
    except StatusLocked as e:
        raise HTTPException(409, str(e)) from e
    db.commit()
    return _to_out(job)


@router.post("/{job_id}/score", response_model=JobOut)
def score_now(job_id: int, db: Session = Depends(get_session)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "job not found")
    try:
        score_job(db, job)
    except Exception as e:
        raise HTTPException(502, str(e)) from e
    return _to_out(job)


@router.post("/{job_id}/prepare", response_model=ApplicationOut)
def prepare_now(job_id: int, force: bool = False, cover: Literal["auto", "always", "never"] = "auto",
                resume_id: int | None = None, db: Session = Depends(get_session)):
    """Create (or with force, refresh) the application. cover: auto = a letter only for strong matches."""
    try:
        return prepare_application(db, job_id, force=force, cover=cover, resume_id=resume_id)
    except AlreadySent as e:
        raise HTTPException(409, str(e)) from e
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        raise HTTPException(502, str(e)) from e


@router.get("/{job_id}/applications", response_model=list[ApplicationOut])
def job_applications(job_id: int, db: Session = Depends(get_session)):
    return db.scalars(select(Application).where(Application.job_id == job_id).order_by(Application.id.desc())).all()


# ---------------------------------------------------------------------------
# Bulk actions and direct apply
# ---------------------------------------------------------------------------


class BulkBody(BaseModel):
    ids: list[int]
    action: Literal["analyze", "prepare", "reject", "requeue"]


@router.post("/bulk")
def bulk(body: BulkBody, db: Session = Depends(get_session)):
    ids = list(dict.fromkeys(body.ids))[:200]
    if not ids:
        raise HTTPException(400, "no jobs selected")
    if body.action in ("reject", "requeue"):
        status = JobStatus.REJECTED if body.action == "reject" else JobStatus.QUEUED
        n = skipped = 0
        for job in db.scalars(select(Job).options(selectinload(Job.applications)).where(Job.id.in_(ids))).all():
            try:
                _set_status(db, job, status)
                n += 1
            except StatusLocked:
                skipped += 1          # jobs with an application keep their state
        db.commit()
        return {"updated": n, "skipped": skipped}
    try:
        if body.action == "analyze":
            from ..pipeline.scoring import score_jobs

            return tasks.start("analyze", f"analyze {len(ids)} selected jobs", lambda d, log: score_jobs(d, ids, log=log))
        return tasks.start("prepare", f"prepare {len(ids)} selected jobs", lambda d, log: _prepare_many(d, ids, log))
    except tasks.TaskBusy as e:
        raise HTTPException(409, str(e)) from e


def _prepare_many(db: Session, ids: list[int], log) -> dict:
    from .. import cancel
    from ..llm.client import LLMBudgetExceeded

    out = {"prepared": 0, "errors": 0, "stopped": ""}
    for jid in ids:
        if cancel.requested():
            out["stopped"] = "stopped by user"
            break
        try:
            app = prepare_application(db, jid, cover="auto")
            out["prepared"] += 1
            log(f"  prepared #{app.id} for job {jid} ({app.status})")
        except LLMBudgetExceeded as e:
            out["stopped"] = str(e)
            break
        except Exception as e:
            db.rollback()
            out["errors"] += 1
            log(f"  ! job {jid}: {e}")
    return out


class ApplyBody(BaseModel):
    mode: Literal["ai", "direct"] = "ai"
    resume_id: int | None = None           # None = the resume of the profile the job matched


def direct_apply(db: Session, job_id: int, mode: str, log, resume_id: int | None = None) -> dict:
    """Get one job ready to submit: (ai) score it if needed and draft a letter for a top match, or (direct) use only
    the answer bank; then fill the form without submitting so the user can review what is missing."""
    from ..pipeline.apply.runner import apply_application

    job = db.get(Job, job_id)
    if job is None:
        raise ValueError(f"job {job_id} not found")
    if mode == "ai" and job.fit_score is None:
        log("scoring the job")
        score_job(db, job, resume=profile_text(db, resume_id) if resume_id else None)
    app = prepare_application(db, job_id, force=False, cover="auto" if mode == "ai" else "never", resume_id=resume_id)
    if app.method == "manual" or apply_method(job) == "manual":
        log("this job is applied to by hand: the letter and answers are ready to copy")
        return {"application_id": app.id, "status": app.status, "manual": True}
    log("filling the form (not submitting)")
    app = apply_application(db, app.id, submit=False, log=log)
    return {"application_id": app.id, "status": app.status, "unanswered": app.unanswered or [], "manual": False}


@router.post("/{job_id}/apply")
def apply_job(job_id: int, body: ApplyBody, db: Session = Depends(get_session)):
    """Start direct apply in the background. Nothing is submitted here; the user confirms on the review screen."""
    if not db.get(Job, job_id):
        raise HTTPException(404, "job not found")
    try:
        return tasks.start("apply", f"get application ready for job #{job_id}",
                           lambda d, log: direct_apply(d, job_id, body.mode, log, body.resume_id))
    except tasks.TaskBusy as e:
        raise HTTPException(409, str(e)) from e
