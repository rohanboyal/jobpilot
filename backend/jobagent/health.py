"""Source health from recent crawl runs, so a site that silently stops returning jobs gets noticed."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Company, Run

_SKIP = re.compile(r"skipped[: ]+(.*)", re.I)
_REFUSED = re.compile(r"HTTP (403|429)\b")
_BOARDS = ("greenhouse", "lever", "ashby", "workable", "smartrecruiters")


def _companies_per_source(db: Session) -> dict[str, int]:
    """How many active tracked companies each company-board source reads (0 = nothing to crawl, not a fault)."""
    counts = dict(db.execute(select(Company.ats_type, func.count()).where(Company.is_active.is_(True))
                             .group_by(Company.ats_type)).all())
    careers = db.scalar(select(func.count()).select_from(Company).where(
        Company.is_active.is_(True), Company.careers_url.is_not(None), Company.ats_type.in_(("custom", "unknown")))) or 0
    return {**{b: counts.get(b, 0) for b in _BOARDS}, "company_careers": careers}


def _fetched(r: Run) -> int:
    return int((r.stats or {}).get("fetched") or 0)


def was_skipped(r: Run) -> bool:
    return bool(_SKIP.search(r.log or ""))


def was_refused(r: Run) -> bool:
    """The site itself turned this run away: a bot check, or HTTP 403/429."""
    return bool((r.stats or {}).get("blocked") or _REFUSED.search(f"{r.error or ''}\n{r.log or ''}"))


def source_health(db: Session, names: list[str] | None = None) -> dict[str, dict[str, Any]]:
    """{source: {'health': ok|idle|empty|blocked|failing|never, 'note': str}} from the last three crawls of each."""
    runs: dict[str, list[Run]] = {}
    for r in db.scalars(select(Run).where(Run.kind == "crawl").order_by(Run.started_at.desc()).limit(600)).all():
        if r.source and len(runs.setdefault(r.source, [])) < 3:
            runs[r.source].append(r)
    tracked = _companies_per_source(db)
    out: dict[str, dict[str, Any]] = {}
    for name in names if names is not None else list(runs):
        rs = runs.get(name) or []
        if tracked.get(name, 1) == 0:
            out[name] = {"health": "idle", "note": "No tracked company uses this job board yet."}
            continue
        if not rs:
            out[name] = {"health": "never", "note": "Not run yet."}
            continue
        last = rs[0]
        stats = last.stats or {}
        skip = _SKIP.search(last.log or "")
        if last.status == "error":
            out[name] = {"health": "failing", "note": (last.error or "The last run failed.")[:200]}
        elif stats.get("blocked") or stats.get("login_required"):
            out[name] = {"health": "blocked", "note": "The site showed a bot check or a login wall. Sign in once, then run it again."}
        elif _fetched(last) == 0 and _REFUSED.search(last.log or ""):
            code = _REFUSED.search(last.log or "").group(1)
            out[name] = {"health": "blocked", "note": f"The site refuses automated visits (HTTP {code}). Turn it off, "
                                                      "or sign in once and try again."}
        elif _fetched(last) == 0 and skip and "resting" in skip.group(1):
            out[name] = {"health": "blocked", "note": f"{skip.group(1).strip()[:160].capitalize()}. Run now tries it sooner."}
        elif _fetched(last) == 0 and skip:
            out[name] = {"health": "idle", "note": f"Skipped: {skip.group(1).strip()[:160]}"}
        elif len(rs) >= 3 and all(_fetched(r) == 0 and not _SKIP.search(r.log or "") for r in rs):
            out[name] = {"health": "empty", "note": "Found nothing in its last 3 runs. The site may have changed its layout."}
        else:
            out[name] = {"health": "ok", "note": ""}
    return out


def attention_count(db: Session, enabled: list[str]) -> list[dict[str, Any]]:
    """Enabled sources that need the user's attention."""
    h = source_health(db, enabled)
    return [{"source": n, **v} for n, v in h.items() if v["health"] in ("failing", "blocked", "empty")]
