from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import tasks
from ..db import get_session
from ..models import Company, Job
from ..pipeline.ingest import run_source
from ..pipeline.prefilter import prefilter_new
from ..schemas import CompanyIn, CompanyOut, CompanyPatch, Page
from ..sources.ats_detect import detect_ats
from ..utils.text import domain_of

router = APIRouter(prefix="/companies", tags=["companies"])


def _with_counts(db: Session, rows: list[Company]) -> list[CompanyOut]:
    ids = [c.id for c in rows]
    counts = dict(db.execute(select(Job.company_id, func.count(Job.id)).where(Job.company_id.in_(ids))
                             .group_by(Job.company_id)).all()) if ids else {}
    out = []
    for c in rows:
        o = CompanyOut.model_validate(c)
        o.job_count = counts.get(c.id, 0)
        out.append(o)
    return out


@router.get("", response_model=Page)
def list_companies(db: Session = Depends(get_session), q: str | None = None, ats: str | None = None,
                   origin: str | None = None, active: bool | None = None, page: int = 1, page_size: int = 50):
    stmt = select(Company)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Company.name.ilike(like), Company.domain.ilike(like), Company.ats_slug.ilike(like)))
    if ats:
        stmt = stmt.where(Company.ats_type == ats)
    if origin:
        stmt = stmt.where(Company.origin == origin)
    if active is not None:
        stmt = stmt.where(Company.is_active.is_(active))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(Company.name).offset((page - 1) * page_size).limit(page_size)).all()
    return Page(items=_with_counts(db, rows), total=total, page=page, page_size=page_size)


@router.post("", response_model=CompanyOut)
def create_company(body: CompanyIn, db: Session = Depends(get_session)):
    ats_type, slug = body.ats_type, body.ats_slug
    for candidate in (body.careers_url, body.website):
        det = detect_ats(candidate)
        if det and (ats_type in ("custom", "unknown") or not slug):
            ats_type, slug = det
    if ats_type not in ("custom", "unknown") and not slug:
        raise HTTPException(400, "ats_slug is required for a known ATS")
    if ats_type in ("custom", "unknown") and not body.careers_url:
        raise HTTPException(400, "careers_url is required when the ATS is not known")
    c = Company(name=body.name.strip(), website=body.website, careers_url=body.careers_url, ats_type=ats_type,
                ats_slug=slug, notes=body.notes, origin="user", domain=domain_of(body.website or body.careers_url))
    db.add(c)
    db.commit()
    return _with_counts(db, [c])[0]


@router.post("/detect")
def detect(url: str):
    det = detect_ats(url)
    return {"ats_type": det[0] if det else None, "ats_slug": det[1] if det else None}


@router.patch("/{company_id}", response_model=CompanyOut)
def patch_company(company_id: int, body: CompanyPatch, db: Session = Depends(get_session)):
    c = db.get(Company, company_id)
    if not c:
        raise HTTPException(404, "company not found")
    data = body.model_dump(exclude_unset=True)
    for k in ("name", "ats_type"):
        if k in data and not (data[k] or "").strip():
            raise HTTPException(400, f"{k} cannot be empty")
    if "name" in data:
        data["name"] = data["name"].strip()
    for k, v in data.items():
        setattr(c, k, v)
    if c.ats_type not in ("custom", "unknown") and not c.ats_slug:
        raise HTTPException(400, "ats_slug is required for a known ATS")
    if "website" in data or "careers_url" in data:
        c.domain = domain_of(c.website or c.careers_url)
    db.commit()
    return _with_counts(db, [c])[0]


@router.delete("/{company_id}")
def delete_company(company_id: int, db: Session = Depends(get_session)):
    c = db.get(Company, company_id)
    if not c:
        raise HTTPException(404, "company not found")
    c.is_active = False
    db.commit()
    return {"ok": True, "note": "deactivated (jobs kept)"}


@router.post("/{company_id}/crawl")
def crawl_company(company_id: int, db: Session = Depends(get_session)):
    c = db.get(Company, company_id)
    if not c:
        raise HTTPException(404, "company not found")
    if not c.is_active:
        raise HTTPException(409, "company is deactivated; activate it first")
    source = c.ats_type if c.ats_type not in ("custom", "unknown") else "company_careers"

    def _run(db2, log):
        run = run_source(source, db2, log, company_ids={company_id})
        out = {"run_id": run.id, "status": run.status, **(run.stats or {})}
        out["prefilter"] = prefilter_new(db2)       # match the new jobs against your profiles (free)
        return out

    try:
        return tasks.start("crawl", f"crawl {c.name}", _run)
    except tasks.TaskBusy as e:
        raise HTTPException(409, str(e)) from e
