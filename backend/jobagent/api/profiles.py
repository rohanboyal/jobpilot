"""Search profiles: list, create, edit, delete, build one from the resume analysis."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from ..config import SearchProfile
from ..db import get_session
from ..models import Job, JobStatus, Profile, SearchProfileRow, utcnow
from ..pipeline.prefilter import rematch
from ..profiles import from_resume_analysis, rows

router = APIRouter(prefix="/profiles", tags=["profiles"])


class ProfileBody(BaseModel):
    name: str
    enabled: bool = True
    search: SearchProfile
    resume_id: int | None = None          # None = the default resume


def _resume_id(db: Session, rid: int | None) -> int | None:
    if rid in (None, 1):
        return None                       # the default resume, whichever file it holds later
    p = db.get(Profile, rid)
    if p is None or not (p.resume_text or "").strip():
        raise HTTPException(400, "that resume doesn't exist or has no text yet")
    return rid


def _count(db: Session, pid: int) -> dict[str, int]:
    q = text("SELECT count(*) FROM jobs WHERE duplicate_of IS NULL AND status IN ('queued','scored','shortlisted') "
             "AND EXISTS (SELECT 1 FROM json_each(jobs.profile_ids) WHERE json_each.value = :pid)")
    return {"matching": db.execute(q, {"pid": pid}).scalar() or 0}


def _out(db: Session, r: SearchProfileRow) -> dict:
    return {"id": r.id, "name": r.name, "enabled": r.enabled, "search": SearchProfile.model_validate(r.data).model_dump(),
            "resume_id": r.resume_id, "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            **_count(db, r.id)}


@router.get("")
def list_profiles(db: Session = Depends(get_session)):
    return [_out(db, r) for r in rows(db)]


@router.post("")
def create_profile(body: ProfileBody, db: Session = Depends(get_session)):
    r = SearchProfileRow(name=body.name.strip() or "New profile", enabled=body.enabled, data=body.search.model_dump(),
                         resume_id=_resume_id(db, body.resume_id))
    db.add(r)
    db.commit()
    stats = rematch(db)
    return {**_out(db, r), "rematch": stats}


@router.put("/{pid}")
def update_profile(pid: int, body: ProfileBody, db: Session = Depends(get_session)):
    r = db.get(SearchProfileRow, pid)
    if not r:
        raise HTTPException(404, "profile not found")
    r.name, r.enabled, r.data = body.name.strip() or r.name, body.enabled, body.search.model_dump()
    rid = _resume_id(db, body.resume_id)
    if rid != (None if r.resume_id == 1 else r.resume_id):
        r.resume_id, r.resume_changed_at = rid, utcnow()       # what it judged so far used the other resume
    db.commit()
    stats = rematch(db)
    return {**_out(db, r), "rematch": stats}


@router.delete("/{pid}")
def delete_profile(pid: int, db: Session = Depends(get_session)):
    r = db.get(SearchProfileRow, pid)
    if not r:
        raise HTTPException(404, "profile not found")
    if db.scalar(select(func.count(SearchProfileRow.id))) <= 1:
        raise HTTPException(409, "keep at least one profile; disable it instead")
    db.delete(r)
    db.commit()
    return {"ok": True, "rematch": rematch(db)}


@router.post("/from-resume")
def from_resume(resume_id: int = 1, db: Session = Depends(get_session)):
    """New profile from a resume's last analysis, using that resume (Analyze must have run; no extra AI call)."""
    p = db.get(Profile, resume_id)
    extra = (p.extra or {}) if p else {}
    if not extra.get("suggested_roles"):
        raise HTTPException(400, "Analyze this resume first; the suggestions come from that analysis.")
    analysis = {**extra, "skills": p.skills or [], "years_experience": p.years_experience}
    first = rows(db)[0]
    sp = from_resume_analysis(analysis, SearchProfile.model_validate(first.data))
    name = f"{sp.roles[0] if sp.roles else 'My roles'} (from {p.name or 'resume'})"[:100]
    r = SearchProfileRow(name=name, enabled=True, data=sp.model_dump(), resume_id=_resume_id(db, resume_id))
    db.add(r)
    db.commit()
    return {**_out(db, r), "rematch": rematch(db)}


@router.get("/stats")
def stats(db: Session = Depends(get_session)):
    queued = db.scalar(select(func.count(Job.id)).where(Job.status == JobStatus.QUEUED, Job.duplicate_of.is_(None))) or 0
    return {"queued": queued}
