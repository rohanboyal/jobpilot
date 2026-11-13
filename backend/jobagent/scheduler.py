"""APScheduler wiring: each pipeline stage runs on its own days and time while the API server is up.

Stage settings live in the DB (`schedule.collect`, `schedule.analyze`, `schedule.prepare`, `schedule.paused`) and are
edited on the Schedule page. Collect is free (crawl + prefilter); Analyze scores the best new matches and, when
Prepare is on, drafts applications for the top ones right after. JOBAGENT_SCHEDULER_ENABLED=false keeps the scheduler
from starting at all (tests).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from tzlocal import get_localzone

from . import tasks
from .config import get_settings
from .db import session_scope
from .models import Run, utcnow
from .settings_store import DEFAULTS, get_setting, set_setting

_scheduler: BackgroundScheduler | None = None
_TIME = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
_DAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
STAGES = ("collect", "analyze")   # stages with their own run times (prepare follows analyze; apply follows approval)


_RETRY_MIN, _RETRIES = 10, 12          # busy: try again every 10 minutes for up to 2 hours


def _run_stage(stage: str, attempt: int = 0) -> None:
    """Start a scheduled stage. If another run is going (Collect running long, a direct apply, Run now, or both
    stages due at once after the Mac wakes), try again later instead of silently skipping until next week."""
    label, fn = {"collect": ("collect jobs", tasks.collect_stage), "analyze": ("analyze matches", tasks.analyze_stage)}[stage]
    try:
        tasks.start(stage, f"scheduled: {label}", fn)
    except tasks.TaskBusy as e:
        if _scheduler and attempt < _RETRIES:
            _scheduler.add_job(_run_stage, DateTrigger(run_date=datetime.now(get_localzone()) + timedelta(minutes=_RETRY_MIN)),
                               args=[stage, attempt + 1], id=f"retry:{stage}", replace_existing=True)
            return
        with session_scope() as db:              # record it, so the Activity log shows why nothing ran
            db.add(Run(kind=stage, status="error", error=f"scheduled run skipped: still busy after 2 hours ({e})",
                       finished_at=utcnow()))
            db.commit()


def _run_collect() -> None:
    _run_stage("collect")


def _run_analyze() -> None:
    _run_stage("analyze")


_RUNNERS = {"collect": _run_collect, "analyze": _run_analyze}


def normalize_time(t: str) -> str:
    m = _TIME.match((t or "").strip())
    if not m:
        raise ValueError(f"'{t}' is not a time of day (use HH:MM, 24-hour)")
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def normalize_times(times: list[str]) -> list[str]:
    """Validate 'H:MM' strings, return sorted unique 'HH:MM'. Raises ValueError on a bad entry."""
    return sorted({normalize_time(t) for t in times})


def normalize_days(days: list[int]) -> list[int]:
    out = sorted({int(d) for d in days})
    if any(d < 0 or d > 6 for d in out):
        raise ValueError("days are 0 (Monday) to 6 (Sunday)")
    return out


def _stage(db, name: str) -> dict[str, Any]:
    return {**DEFAULTS[f"schedule.{name}"], **(get_setting(db, f"schedule.{name}") or {})}


def config() -> dict[str, Any]:
    with session_scope() as db:
        return {
            "paused": bool(get_setting(db, "schedule.paused")),
            "collect": _stage(db, "collect"),
            "analyze": _stage(db, "analyze"),
            "prepare": _stage(db, "prepare"),
            "apply_mode": get_setting(db, "apply.mode") or "approve",
        }


def _apply() -> None:
    """Make the scheduler's jobs match the saved settings."""
    if not _scheduler:
        return
    for job in _scheduler.get_jobs():
        job.remove()
    cfg = config()
    if cfg["paused"]:
        return
    tz = get_localzone()
    for name in STAGES:
        st = cfg[name]
        if not st.get("enabled") or not st.get("days"):
            continue
        try:
            hh, mm = normalize_time(st.get("time") or "").split(":")
        except ValueError:
            continue
        dow = ",".join(_DAY_NAMES[d] for d in normalize_days(st["days"]))
        _scheduler.add_job(_RUNNERS[name], CronTrigger(day_of_week=dow, hour=int(hh), minute=int(mm), timezone=tz),
                           id=f"stage:{name}", coalesce=True, max_instances=1,
                           misfire_grace_time=2 * 3600)   # Mac asleep: run on wake within 2 hours


def start() -> None:
    global _scheduler
    if not get_settings().scheduler_enabled or _scheduler:
        return
    _scheduler = BackgroundScheduler(timezone=get_localzone())
    _scheduler.start()
    _apply()


def stop() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def _next(name: str) -> str | None:
    job = _scheduler.get_job(f"stage:{name}") if _scheduler else None
    return job.next_run_time.isoformat() if job and job.next_run_time else None


def ai_collect_calls_per_run(profile_ids: list[int] | None = None) -> int:
    """AI calls one Collect makes at most: pages read by the AI because a site has no selectors. Mirrors the crawl:
    each site searches up to 2 job titles (at least one per profile) x 2 places (if its URL takes a place) x its
    pages, capped per run."""
    from .health import _companies_per_source
    from .profiles import enabled_profiles, merge
    from .settings_store import enabled_sources
    from .sources.base import all_sources
    from .sources.generic_sites import load_sites

    s = get_settings()
    sites = {f"site_{x['key']}": x for x in load_sites()}
    with session_scope() as db:
        enabled = enabled_sources(db)
        selected = enabled_profiles(db, profile_ids)
        search = merge([p for _, p in selected])
        careers = _companies_per_source(db)["company_careers"]
    titles = min(max(2, len(selected)), len([r for r in search.roles if r.strip()]) or 1)
    places = min(2, len([x for x in search.locations if x.strip() and x.strip().lower() != "remote"]) or 1)
    countries = {c.lower() for c in search.countries}
    calls = 0
    for name, cls in all_sources().items():
        if not enabled.get(name) or not cls.uses_ai:
            continue
        if name == "company_careers":
            calls += min(careers, s.max_company_pages_per_run)
            continue
        site = sites.get(name)
        if site is None:
            calls += 2
            continue
        if site.get("card_selector"):
            continue                       # selectors make it free
        wanted = {c.lower() for c in site.get("countries") or []}
        if wanted and not wanted & countries:
            continue                       # skipped for this profile's countries
        searches = titles * (places if "{location" in site["search_url"] else 1) * int(site.get("pages") or 1)
        calls += min(searches, s.max_company_pages_per_run)
    return calls


def info() -> dict[str, Any]:
    cfg = config()
    stages = {name: {**cfg[name], "next_run_at": _next(name)} for name in STAGES}
    upcoming = sorted(x for x in (stages[n]["next_run_at"] for n in STAGES) if x)
    return {
        "available": bool(_scheduler),       # false when JOBAGENT_SCHEDULER_ENABLED=false
        "paused": cfg["paused"],
        "timezone": str(get_localzone()),
        "stages": stages,
        "prepare": cfg["prepare"],
        "apply_mode": cfg["apply_mode"],
        "auto_submit_allowed": get_settings().auto_submit,
        "next_run_at": upcoming[0] if upcoming else None,
        "collect_ai_per_run": ai_collect_calls_per_run(),
        "running": tasks.running(),
    }


def configure(body: dict[str, Any]) -> dict[str, Any]:
    """Persist schedule changes and reschedule. Raises ValueError for malformed input."""
    writes: list[tuple[str, Any]] = []          # everything is checked first, then saved, then applied
    with session_scope() as db:
        if body.get("paused") is not None:
            writes.append(("schedule.paused", bool(body["paused"])))
        for name in ("collect", "analyze", "prepare"):
            patch = body.get(name)
            if patch is None:
                continue
            cur = _stage(db, name)
            if "enabled" in patch:
                cur["enabled"] = bool(patch["enabled"])
            if "days" in patch:
                cur["days"] = normalize_days(patch["days"])
            if "time" in patch:
                cur["time"] = normalize_time(patch["time"])
            if "limit" in patch:
                lim = int(patch["limit"])
                if not 0 <= lim <= 200:
                    raise ValueError("limit must be between 0 and 200")
                cur["limit"] = lim
            if "min_fit" in patch:
                mf = int(patch["min_fit"])
                if not 0 <= mf <= 100:
                    raise ValueError("min_fit must be between 0 and 100")
                cur["min_fit"] = mf
            writes.append((f"schedule.{name}", cur))
        mode = body.get("apply_mode")
        if mode is not None:
            if mode not in ("approve", "auto", "manual"):
                raise ValueError("apply_mode must be approve, auto or manual")
            if mode == "auto" and not get_settings().auto_submit:
                raise ValueError("auto-submit is disabled: set JOBAGENT_AUTO_SUBMIT=true in .env first")
            writes.append(("apply.mode", mode))
        for key, value in writes:
            set_setting(db, key, value)
    _apply()
    return info()


PLANS: dict[str, dict[str, Any]] = {
    "light": {"paused": False, "collect": {"enabled": True, "days": [0, 1, 2, 3, 4, 5, 6], "time": "08:00"},
              "analyze": {"enabled": True, "days": [0, 3], "time": "09:00", "limit": 30},
              "prepare": {"enabled": True, "limit": 6}},
    "active": {"paused": False, "collect": {"enabled": True, "days": [0, 1, 2, 3, 4, 5, 6], "time": "08:00"},
               "analyze": {"enabled": True, "days": [0, 1, 2, 3, 4], "time": "09:00", "limit": 30},
               "prepare": {"enabled": True, "limit": 6}},
    "manual": {"paused": True},
}


def apply_plan(plan: str) -> dict[str, Any]:
    if plan not in PLANS:
        raise ValueError(f"unknown plan {plan}")
    return configure(PLANS[plan])
