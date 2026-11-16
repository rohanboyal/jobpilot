"""First-run helpers: create tables, seed companies from config/companies.yaml, ensure the profile row."""

from __future__ import annotations

import os

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import load_company_seeds
from .db import init_db, session_scope
from .models import Application, ApplicationStatus, Company, Profile, Run, utcnow
from .utils.text import domain_of


def seed_companies(db: Session) -> dict[str, int]:
    added = updated = 0
    for seed in load_company_seeds():
        q = select(Company)
        if seed.slug:
            q = q.where(Company.ats_type == seed.ats, Company.ats_slug == seed.slug)
        else:
            q = q.where(Company.name == seed.name)
        existing = db.scalars(q).first()
        if existing:
            changed = False
            for attr, val in (("website", seed.website), ("careers_url", seed.careers_url), ("name", seed.name)):
                if val and getattr(existing, attr) != val:
                    setattr(existing, attr, val)
                    changed = True
            updated += int(changed)
            continue
        db.add(Company(name=seed.name, ats_type=seed.ats, ats_slug=seed.slug, website=seed.website,
                       careers_url=seed.careers_url, domain=domain_of(seed.website), origin="seed"))
        added += 1
    db.commit()
    return {"added": added, "updated": updated}


def ensure_profile(db: Session) -> Profile:
    p = db.get(Profile, 1)
    if p is None:
        p = Profile(id=1)
        db.add(p)
        db.commit()
    return p


def _alive(pid: int | None) -> bool:
    """True if another process with this id is still running (a CLI fill or crawl, say)."""
    from .utils.proc import pid_alive

    return bool(pid) and pid != os.getpid() and pid_alive(pid)


def recover_interrupted(db: Session) -> int:
    """Server start only. A fill/submit or run still marked in progress whose process is gone was cut off by a restart
    and is released; one whose process still runs (a CLI command started while the server restarted) is left alone.
    submitted_at is never touched, so an application whose submit was clicked stays locked until the user checks."""
    n = 0
    for a in db.scalars(select(Application).where(Application.status == ApplicationStatus.SUBMITTING)).all():
        if _alive(a.worker_pid):
            continue
        a.status = ApplicationStatus.NEEDS_REVIEW
        a.error = "interrupted while filling or submitting (server restarted); check the ATS before trying again"
        n += 1
    for r in db.scalars(select(Run).where(Run.status == "running")).all():
        if not _alive(r.worker_pid):
            r.status, r.error, r.finished_at = "error", "interrupted (server restarted)", utcnow()
    db.commit()
    return n


def bootstrap(recover: bool = False) -> dict[str, int]:
    init_db()
    from .pipeline.prefilter import rematch
    from .profiles import ensure_seeded

    with session_scope() as db:
        stats = seed_companies(db)
        ensure_profile(db)
        if recover:
            stats["recovered"] = recover_interrupted(db)
        from .settings_store import get_setting, set_setting

        seeded = ensure_seeded(db)
        if seeded or not get_setting(db, "jobs.annotated_v1"):
            # first profile, or jobs collected before experience/work-mode/salary were read: tag them once (free)
            stats["profile_tagged"] = rematch(db)["checked"]
            set_setting(db, "jobs.annotated_v1", True)
    return stats
