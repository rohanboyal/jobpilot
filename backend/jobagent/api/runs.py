from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import Run
from ..schemas import RunDetail, RunOut

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("", response_model=list[RunOut])
def list_runs(db: Session = Depends(get_session), kind: str | None = None, source: str | None = None, limit: int = 50):
    stmt = select(Run)
    if kind:
        stmt = stmt.where(Run.kind == kind)
    if source:
        stmt = stmt.where(Run.source == source)
    return db.scalars(stmt.order_by(Run.started_at.desc()).limit(min(limit, 500))).all()


@router.get("/{run_id}", response_model=RunDetail)
def get_run(run_id: int, db: Session = Depends(get_session)):
    r = db.get(Run, run_id)
    if not r:
        raise HTTPException(404, "run not found")
    return r
