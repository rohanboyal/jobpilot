"""Resumes: several files, one per kind of job say. Row 1 is the default for profiles that don't pick one."""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..bootstrap import ensure_profile
from ..db import get_session
from ..models import Application, ApplicationStatus, Profile, SearchProfileRow, utcnow
from ..pipeline.profile import analyze_profile, import_resume, resume_row
from ..schemas import ProfileIn, ProfileOut

router = APIRouter(prefix="/resumes", tags=["resumes"])

_SENT = (ApplicationStatus.SUBMITTING, ApplicationStatus.SUBMITTED)
_CONTENT = [c.key for c in Profile.__table__.columns if c.key != "id"]     # what makes a resume, moved as a whole


async def save_upload(db: Session, file: UploadFile, resume_id: int | None, name: str | None = None) -> Profile:
    """Read an uploaded resume into `resume_id` (None = a new resume)."""
    suffix = Path(file.filename or "resume.pdf").suffix.lower()
    if suffix not in (".pdf", ".docx", ".txt", ".md"):
        raise HTTPException(400, "upload a .pdf, .docx, .txt or .md file")
    data = await file.read()
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(data)
        tmp_path = Path(tmp.name)
    try:
        return import_resume(db, tmp_path, file.filename, resume_id=resume_id, name=name)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    finally:
        tmp_path.unlink(missing_ok=True)


def _get(db: Session, rid: int) -> Profile:
    p = ensure_profile(db) if rid == 1 else db.get(Profile, rid)
    if p is None:
        raise HTTPException(404, "resume not found")
    return p


@router.get("")
def list_resumes(db: Session = Depends(get_session)):
    """Every resume with the search profiles that use it (a profile without its own resume uses the default)."""
    ensure_profile(db)
    used: dict[int, list[dict]] = {}
    for r in db.scalars(select(SearchProfileRow).order_by(SearchProfileRow.id)).all():
        rid = r.resume_id if r.resume_id and db.get(Profile, r.resume_id) else 1
        used.setdefault(rid, []).append({"id": r.id, "name": r.name})
    return [{
        "id": p.id, "name": p.name or ("Main resume" if p.id == 1 else f"Resume {p.id}"), "is_default": p.id == 1,
        "resume_filename": p.resume_filename, "has_text": bool((p.resume_text or "").strip()),
        "uploaded_at": (p.extra or {}).get("resume_uploaded_at"), "updated_at": p.updated_at.isoformat(),
        "headline": p.headline, "skills": (p.skills or [])[:12], "years_experience": p.years_experience,
        "used_by": used.get(p.id, []),
    } for p in db.scalars(select(Profile).order_by(Profile.id)).all()]


@router.post("", response_model=ProfileOut)
async def add_resume(file: UploadFile = File(...), name: str | None = Form(None), db: Session = Depends(get_session)):
    ensure_profile(db)
    default = db.get(Profile, 1)
    # The first resume fills the default slot, so profiles without their own resume use it.
    target = 1 if default and not (default.resume_text or "").strip() else None
    return await save_upload(db, file, target, name)


@router.get("/{rid}", response_model=ProfileOut)
def get_resume(rid: int, db: Session = Depends(get_session)):
    return _get(db, rid)


@router.put("/{rid}", response_model=ProfileOut)
def update_resume(rid: int, body: ProfileIn, db: Session = Depends(get_session)):
    p = _get(db, rid)
    data = body.model_dump(exclude_unset=True)
    extra = data.pop("extra", None)
    if "name" in data:
        data["name"] = (data["name"] or "").strip()[:120] or p.name
    for k, v in data.items():
        setattr(p, k, v)
    if extra is not None:
        p.extra = {**(p.extra or {}), **extra}
    db.commit()
    return p


@router.post("/{rid}/file", response_model=ProfileOut)
async def replace_file(rid: int, file: UploadFile = File(...), db: Session = Depends(get_session)):
    _get(db, rid)
    return await save_upload(db, file, rid)


@router.post("/{rid}/analyze")
def analyze(rid: int, db: Session = Depends(get_session)):
    _get(db, rid)
    try:
        return analyze_profile(db, rid)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        raise HTTPException(502, str(e)) from e


def _not_sent(a: Application) -> bool:
    return a.status not in _SENT and a.submitted_at is None


def _unlink_unused(db: Session, paths: set[str]) -> None:
    """Remove resume files nothing points to any more. A sent application's file stays: it is part of its record."""
    used = set(db.scalars(select(Profile.resume_path).where(Profile.resume_path.is_not(None))))
    used |= set(db.scalars(select(Application.resume_path).where(Application.resume_path.is_not(None))))
    for path in paths - used:
        Path(path).unlink(missing_ok=True)


@router.delete("/{rid}")
def delete_resume(rid: int, db: Session = Depends(get_session)):
    """Delete any resume. Profiles and unsent applications that used it move to the default resume. Deleting the
    default moves the next resume into its place (row 1 stays the default); deleting the only one leaves none.
    Sent applications keep the file they were sent with. Profiles that end up on another resume are marked, so
    Refresh redoes what was judged with the old one."""
    gone = _get(db, rid)
    ensure_profile(db)
    heir = None
    if rid == 1:
        others = db.scalars(select(Profile).where(Profile.id != 1).order_by(Profile.id)).all()
        heir = min(others, key=lambda r: (not (r.resume_text or "").strip(), r.id), default=None)
    removed = heir.id if heir else None if rid == 1 else rid      # the row that disappears: never the default one
    now = utcnow()
    for r in db.scalars(select(SearchProfileRow)).all():
        if (resume_row(db, r.resume_id) or gone).id == rid:
            r.resume_changed_at = now
        if r.resume_id in (1, removed) or (r.resume_id and db.get(Profile, r.resume_id) is None):  # None: the default
            r.resume_id = None
    old = {x for x in (gone.resume_path,) if x}
    moving = {rid, heir.id} if heir else {rid}
    for a in db.scalars(select(Application).where(Application.resume_id.in_(moving)
                                                  | Application.resume_id.is_(None))).all():
        if heir is not None and a.resume_id == heir.id:
            a.resume_id = None                    # the heir's own applications: same file, now in the default row
        elif (a.resume_id or 1) == rid and _not_sent(a):
            a.resume_id = None
            a.resume_path = heir.resume_path if heir else None if rid == 1 else db.get(Profile, 1).resume_path
    if heir is not None:
        for col in _CONTENT:
            setattr(gone, col, getattr(heir, col))
        db.delete(heir)
    elif rid == 1:
        for col in _CONTENT:
            setattr(gone, col, None)
        gone.updated_at = now
    else:
        db.delete(gone)
    db.commit()
    _unlink_unused(db, old)
    default = db.get(Profile, 1)
    return {"ok": True, "removed": removed,
            "default": default.name if default and (default.resume_text or "").strip() else None}
