from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import tasks
from ..bootstrap import ensure_profile
from ..db import get_session
from ..models import Application, ApplicationStatus, Job, JobStatus, Profile, SearchProfileRow
from ..pipeline.profile import analyze_profile
from ..profiles import enabled_profiles
from ..schemas import ProfileIn, ProfileOut
from .resumes import save_upload

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("", response_model=ProfileOut)
def get_profile(db: Session = Depends(get_session)):
    return ensure_profile(db)


@router.put("", response_model=ProfileOut)
def update_profile(body: ProfileIn, db: Session = Depends(get_session)):
    p = ensure_profile(db)
    data = body.model_dump(exclude_unset=True)
    extra = data.pop("extra", None)
    for k, v in data.items():
        setattr(p, k, v)
    if extra is not None:
        p.extra = {**(p.extra or {}), **extra}
    db.commit()
    return p


def _resume_since(p) -> datetime | None:
    """When the current resume was uploaded (older uploads predate the field: use the file's time)."""
    raw = (p.extra or {}).get("resume_uploaded_at")
    if raw:
        return datetime.fromisoformat(raw)
    if p.resume_path and Path(p.resume_path).exists():
        return datetime.fromtimestamp(Path(p.resume_path).stat().st_mtime, UTC).replace(tzinfo=None)
    return None


def _stale(db: Session) -> dict:
    """Scores and letters made before the resume they depend on was uploaded (each profile may use its own), or before
    their profile started using another resume."""
    ensure_profile(db)
    since = {p.id: _resume_since(p) for p in db.scalars(select(Profile)).all() if (p.resume_text or "").strip()}
    if not any(since.values()):
        return {"since": None, "job_ids": [], "app_ids": [], "app_job_ids": []}
    picks = {r.id: (r.resume_id, r.resume_changed_at) for r in db.scalars(select(SearchProfileRow)).all()}
    on = [pid for pid, _ in enabled_profiles(db)]
    latest = max([s for s in since.values() if s] + [c for _, c in picks.values() if c])

    def judged(profile_ids: list[int] | None) -> tuple[datetime | None, datetime | None]:
        """When the resume a job is judged with was uploaded, and when its profile switched to it (mirrors
        pick_profile + resume_row)."""
        pid = next((i for i in profile_ids or [] if i in on), None)
        rid, changed = picks.get(pid, (None, None)) if pid else (None, None)
        return since.get(rid if rid in since else 1), changed

    def need(uploaded: datetime | None, changed: datetime | None) -> datetime | None:
        return max(uploaded, changed) if uploaded and changed else uploaded       # no resume: nothing to redo with

    jobs = db.scalars(select(Job).where(Job.scored_at < latest,
                                        Job.duplicate_of.is_(None),
                                        Job.status.in_([JobStatus.SCORED, JobStatus.SHORTLISTED]))).all()
    job_ids = [j.id for j in jobs if (t := need(*judged(j.profile_ids))) and j.scored_at < t]
    drafted = func.coalesce(Application.drafted_at, Application.created_at)      # redrafting reuses the row
    apps = db.scalars(select(Application).where(Application.status == ApplicationStatus.NEEDS_REVIEW,
                                                Application.submitted_at.is_(None), Application.cover_letter.is_not(None),
                                                drafted < latest)).all()

    def letter_needs(a: Application) -> datetime | None:
        uploaded = since.get(a.resume_id if a.resume_id in since else 1)
        # No resume of its own (it follows its profile, e.g. after its resume was deleted): the profile's switch counts.
        return need(uploaded, judged(a.job.profile_ids)[1]) if a.resume_id is None else uploaded

    apps = [a for a in apps if a.cover_letter and (t := letter_needs(a)) and (a.drafted_at or a.created_at) < t]
    return {"since": latest.isoformat(), "job_ids": job_ids, "app_ids": [a.id for a in apps],
            "app_job_ids": [a.job_id for a in apps]}


@router.get("/stale")
def stale(db: Session = Depends(get_session)):
    """Scores and draft cover letters made before the current resume was uploaded."""
    s = _stale(db)
    return {"since": s["since"], "jobs": len(s["job_ids"]), "drafts": len(s["app_ids"])}


@router.post("/refresh")
def refresh(db: Session = Depends(get_session)):
    """Re-score those jobs and redraft those letters with the current resume (one AI call each)."""
    s = _stale(db)
    if not s["job_ids"] and not s["app_ids"]:
        raise HTTPException(404, "nothing was made with an older resume")

    def _run(db2, log):
        from .. import cancel
        from ..llm.client import LLMBudgetExceeded
        from ..pipeline.prepare import AlreadySent, prepare_application
        from ..pipeline.scoring import score_jobs

        out = {"rescore": score_jobs(db2, s["job_ids"] + s["app_job_ids"], log=log), "redrafted": 0, "stopped": ""}
        for jid in s["app_job_ids"]:
            if cancel.requested():
                out["stopped"] = "stopped by user"
                break
            try:
                app = prepare_application(db2, jid, force=True, cover="auto")
            except LLMBudgetExceeded as e:
                out["stopped"] = str(e)
                log(f"stop: {e}")
                break
            except AlreadySent:
                continue                       # sent meanwhile: left exactly as it is
            out["redrafted"] += 1
            log(f"  job {jid}: " + {"new": "new cover letter", "kept": "kept the earlier letter (fit is now below the "
                                    "cover-letter threshold)", "none": "no letter (fit is below the threshold)"}
                [getattr(app, "cover_state", "new")])
        return out

    try:
        return tasks.start("analyze", "refresh with your current resume", _run)
    except tasks.TaskBusy as e:
        raise HTTPException(409, str(e)) from e


@router.get("/contact")
def contact_suggestions(db: Session = Depends(get_session)):
    """Answer-bank values read from the resume, for the user to accept. Only what the resume states."""
    p = ensure_profile(db)
    c = (p.extra or {}).get("contact") or {}
    full = (c.get("full_name") or "").strip()
    out = {
        "full_name": full, "email": c.get("email") or "", "phone": c.get("phone") or "",
        "current_location": c.get("location") or "", "linkedin_url": c.get("linkedin") or "",
        "github_url": c.get("github") or "", "portfolio_url": c.get("portfolio") or "",
        "years_of_experience": f"{p.years_experience:g}" if p.years_experience is not None else "",
    }
    if full and " " in full:
        out["first_name"], out["last_name"] = full.split()[0], " ".join(full.split()[1:])
    return {k: v for k, v in out.items() if v}


@router.post("/resume", response_model=ProfileOut)
async def upload_resume(file: UploadFile = File(...), db: Session = Depends(get_session)):
    """Replace the default resume's file (other resumes: /resumes)."""
    return await save_upload(db, file, 1)


@router.post("/analyze")
def analyze(db: Session = Depends(get_session)):
    try:
        return analyze_profile(db)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        raise HTTPException(502, str(e)) from e
