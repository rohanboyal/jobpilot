from __future__ import annotations

import subprocess
import sys

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import pacing, scheduler, tasks
from ..config import get_settings
from ..db import get_session
from ..llm.client import budget_status, provider_status
from ..pipeline.apply.runner import submit_approved
from ..pipeline.discover import discover_companies
from ..pipeline.ingest import crawl_all
from ..pipeline.prefilter import prefilter_new
from ..pipeline.prepare import prepare_shortlisted
from ..pipeline.scoring import score_queued
from ..profiles import enabled_profiles, names
from ..schemas import PipelineRequest
from ..sources.base import all_sources

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


def _start(kind: str, label: str, fn, *args, **kwargs):
    try:
        return tasks.start(kind, label, fn, *args, **kwargs)
    except tasks.TaskBusy as e:
        raise HTTPException(409, str(e)) from e


def _profiles(db: Session, body: PipelineRequest | None) -> tuple[dict, str]:
    """The run's profile choice as task kwargs, and a label suffix. Only profiles that are on and have titles count."""
    ids = body.profile_ids if body else None
    one_by_one = bool(body and body.one_by_one)
    if ids is not None:
        ok = {pid for pid, _ in enabled_profiles(db)}
        if not ids or any(i not in ok for i in ids):
            raise HTTPException(400, "choose at least one profile that is turned on and has job titles")
    label = ("" if ids is None else f" for {names(db, ids)}") + (" one after another" if one_by_one else "")
    return {"profile_ids": ids, "one_by_one": one_by_one}, label


@router.get("/tasks")
def list_tasks():
    return {"tasks": tasks.list_tasks(), "running": tasks.running(), "scheduler": scheduler.info()}


@router.get("/tasks/{task_id}")
def get_task(task_id: str):
    t = tasks.get_task(task_id)
    if not t:
        raise HTTPException(404, "task not found")
    return t


@router.post("/stop")
def stop_tasks(task_id: str | None = None):
    """Stop the running task (or one task by id) after its current step. Nothing is cut off mid-form."""
    stopped = tasks.stop(task_id)
    if not stopped:
        raise HTTPException(404, "nothing is running")
    return {"stopping": stopped}


@router.post("/crawl")
def crawl(body: PipelineRequest | None = None):
    sources = body.sources if body else None
    if sources:
        unknown = [s for s in sources if s not in all_sources()]
        if unknown:
            raise HTTPException(400, f"unknown sources: {unknown}")
    label = "crawl " + (", ".join(sources) if sources else "all enabled sources")

    def _run(db, log):
        runs = crawl_all(db, only=sources, log=log)
        out = {r.source: {"status": r.status, **(r.stats or {})} for r in runs}
        log("## prefilter")
        out["prefilter"] = prefilter_new(db)
        return out

    return _start("crawl", label, _run)


@router.post("/prefilter")
def prefilter(db: Session = Depends(get_session)):
    return prefilter_new(db)


@router.post("/score")
def score(body: PipelineRequest | None = None):
    limit = body.limit if body else None
    return _start("score", "score queued jobs", lambda db, log: score_queued(db, limit=limit, log=log))


@router.post("/prepare")
def prepare(body: PipelineRequest | None = None):
    limit = body.limit if body else None
    return _start("prepare", "prepare shortlisted", lambda db, log: prepare_shortlisted(db, limit=limit, log=log))


@router.post("/submit-approved")
def submit(body: PipelineRequest | None = None):
    return _start("apply", "submit approved applications",
                  lambda db, log: submit_approved(db, log=log, limit=(body.limit if body and body.limit else 5)))


@router.post("/discover")
def discover():
    return _start("discover", "discover companies", lambda db, log: discover_companies(db, log=log))


@router.post("/collect")
def collect(body: PipelineRequest | None = None, db: Session = Depends(get_session)):
    sources = body.sources if body else None
    kw, label = _profiles(db, body)
    return _start("collect", "collect jobs" + label, tasks.collect_stage, sources=sources, **kw)


@router.post("/analyze")
def analyze(body: PipelineRequest | None = None, db: Session = Depends(get_session)):
    limit = body.limit if body else None
    kw, label = _profiles(db, body)
    return _start("analyze", "analyze matches" + label, tasks.analyze_stage, limit=limit, **kw)


@router.post("/cycle")
def cycle(body: PipelineRequest | None = None, db: Session = Depends(get_session)):
    sources = body.sources if body else None
    kw, label = _profiles(db, body)
    return _start("cycle", "full cycle" + label, tasks.full_cycle, sources=sources, **kw)


@router.get("/estimate")
def estimate(stage: str = "cycle", profile_ids: str | None = None, one_by_one: bool = False,
             db: Session = Depends(get_session)):
    """At most how many AI calls a run would make, for the Run dialog. profile_ids: comma-separated (none = all on)."""
    from ..llm.client import budget_status
    from ..models import Job, JobStatus
    from ..pipeline.prepare import _setting_int
    from ..profiles import matches_any
    from ..settings_store import get_setting

    ids = [int(x) for x in profile_ids.split(",") if x.strip()] if profile_ids else None
    passes = [[pid] for pid, _ in enabled_profiles(db, ids)] if one_by_one else [ids]
    analyze_limit = _setting_int(get_setting(db, "schedule.analyze") or {}, "limit", 30)
    prep = get_setting(db, "schedule.prepare") or {}
    prepare_limit = _setting_int(prep, "limit", 6) if prep.get("enabled", True) else 0
    collect = analyze = 0
    for p in passes:
        if stage in ("cycle", "collect"):
            collect += scheduler.ai_collect_calls_per_run(p)
        if stage in ("cycle", "analyze"):
            queued = analyze_limit
            if stage == "analyze":         # nothing new arrives first: only what is waiting can be scored
                q = select(func.count(Job.id)).where(Job.status == JobStatus.QUEUED, Job.duplicate_of.is_(None))
                queued = min(analyze_limit, db.scalar(q.where(matches_any(p)) if p else q) or 0)
            analyze += queued + (min(prepare_limit, queued) if queued else 0)
    b = budget_status(db)
    left = min(b["window_5h"]["max"] - b["window_5h"]["used"], b["day"]["max"] - b["day"]["used"])
    return {"collect_ai": collect, "analyze_ai": analyze, "total_ai": collect + analyze, "left": max(0, left)}


def _login_url(site: str) -> tuple[str, str | None]:
    """The sign-in page for a source name (or a full URL), and the source it belongs to."""
    url = source = None
    for name, cls in all_sources().items():
        if name == site or name == f"site_{site}":
            url, source = getattr(cls, "login_url", None), name
            break
    defaults = {"indeed": "https://secure.indeed.com/account/login", "naukri": "https://www.naukri.com/nlogin/login",
                "linkedin": "https://www.linkedin.com/login", "shine": "https://www.shine.com/myshine/login/"}
    url = url or defaults.get(site)
    if not url:
        if site.startswith("http"):
            url = site
        else:
            raise HTTPException(400, f"no login url known for '{site}'; pass a full URL instead")
    return url, source


@router.post("/browser-login")
def browser_login(site: str, request: Request, db: Session = Depends(get_session)):
    """Open a visible window on the site's login page with JobPilot's own profile. Close it when done.

    The window opens in the browser the user clicked from when it is installed (Chrome or Edge, a separate profile:
    their own browser data and the system's default browser are left alone); otherwise in JobPilot's Chromium."""
    from ..browser import CHANNELS, browser_label, channel_for_user_agent, profile_in_use
    from ..settings_store import get_setting, set_setting

    url, source = _login_url(site)
    if profile_in_use():
        busy = "a run is reading job sites right now" if tasks.running() else "a sign-in window is still open"
        raise HTTPException(409, f"JobPilot's browser is busy: {busy}. Close that window, or wait for the run to finish "
                                 "(or press Stop), then try again.")
    wanted = channel_for_user_agent(request.headers.get("user-agent", ""))
    if wanted and wanted != get_setting(db, "browser.channel"):
        set_setting(db, "browser.channel", wanted)          # from now on every browser task uses it (one profile)
    log = get_settings().data_dir / "browser-login.log"
    with open(log, "w") as out:
        proc = subprocess.Popen([sys.executable, "-m", "jobagent.cli", "browser-login", url], start_new_session=True,
                                stdout=out, stderr=subprocess.STDOUT)
    try:
        code = proc.wait(timeout=6)            # a window that opens keeps running; a failure exits within seconds
    except subprocess.TimeoutExpired:
        code = None
    if code not in (None, 0):
        tail = " ".join(log.read_text(errors="replace").split()[-60:])
        raise HTTPException(502, f"The sign-in window could not open: {tail[-400:]}")
    if source:
        pacing.mark_signed_in(db, source)
    where = browser_label()
    extra = " (a separate JobPilot profile: your own browsing data isn't touched)" if where in \
        [str(c["label"]) for c in CHANNELS.values()] else ""
    return {"ok": True, "url": url, "browser": where,
            "note": f"A {where} window opened{extra}. Sign in there, then close the window."}


@router.delete("/browser-login")
def forget_browser_login(site: str, db: Session = Depends(get_session)):
    """Sign out: delete the site's cookies from JobPilot's own profile, and read it at the normal pace again."""
    from ..browser import profile_in_use, sign_out_of
    from ..utils.text import domain_of

    try:
        url, _ = _login_url(site)
    except HTTPException:
        url = ""
    domain = domain_of(url) if url else None
    removed = 0
    if domain:
        if profile_in_use():
            busy = "a run is reading job sites right now" if tasks.running() else "a sign-in window is still open"
            raise HTTPException(409, f"JobPilot's browser is busy: {busy}. Try signing out when it's free.")
        removed = sign_out_of(domain)
    pacing.mark_signed_in(db, site, on=False)
    return {"ok": True, "domain": domain, "removed": removed}


@router.get("/health")
def health(db: Session = Depends(get_session)):
    s = get_settings()
    return {"ok": True, "llm": provider_status(), "budget": budget_status(db), "db": str(s.db_path),
            "scheduler": scheduler.info(), "running": tasks.running()}
