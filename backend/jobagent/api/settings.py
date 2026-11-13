from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import scheduler
from ..config import (
    AnswerBank,
    SearchProfile,
    get_settings,
    load_answer_bank,
    load_search_profile,
    save_answer_bank,
    save_search_profile,
)
from ..db import get_session
from ..llm.client import budget_status, provider_status
from ..models import Job, Run
from ..schemas import RunOut, SiteIn, SourceOut
from ..settings_store import DEFAULTS, enabled_sources, runtime_settings, set_setting, set_source_enabled
from ..sources.base import all_sources
from ..sources.generic_sites import load_sites, save_sites

router = APIRouter(prefix="/settings", tags=["settings"])


def _sources(db: Session) -> list[SourceOut]:
    enabled = enabled_sources(db)
    last_runs: dict[str, Run] = {}
    for r in db.scalars(select(Run).where(Run.kind == "crawl").order_by(Run.started_at.desc()).limit(300)).all():
        if r.source and r.source not in last_runs:
            last_runs[r.source] = r
    counts = dict(db.execute(select(Job.source, func.count(Job.id)).group_by(Job.source)).all())
    from ..health import source_health
    from ..pacing import signed_in_sites

    health = source_health(db, list(all_sources()))
    signed_in = signed_in_sites(db)
    out = []
    for name, cls in sorted(all_sources().items(), key=lambda kv: ({"ats": 0, "board": 1, "browser": 2}.get(kv[1].kind, 3), kv[1].label)):
        out.append(SourceOut(
            name=name, label=cls.label, kind=cls.kind, description=cls.description, enabled=enabled.get(name, False),
            default_enabled=cls.default_enabled, needs_browser=cls.needs_browser, uses_ai=cls.uses_ai,
            fragile=cls.fragile, login_url=getattr(cls, "login_url", None),
            signed_in=cls.needs_browser and name in signed_in,
            last_run=RunOut.model_validate(last_runs[name]) if name in last_runs else None, job_count=counts.get(name, 0),
            health=health[name]["health"], health_note=health[name]["note"],
        ))
    return out


@router.get("")
def get_all(db: Session = Depends(get_session)) -> dict[str, Any]:
    s = get_settings()
    return {
        "search": load_search_profile(s).model_dump(),
        "answer_bank": load_answer_bank(s).model_dump(),
        "sources": [x.model_dump() for x in _sources(db)],
        "sites": load_sites(),
        "runtime": runtime_settings(db),
        "runtime_defaults": {k: v for k, v in DEFAULTS.items() if k != "sources.enabled"},
        "env": {
            "llm_model": s.llm_model or "Codex default", "llm_effort": s.llm_effort,
            "llm_max_calls_per_5h": s.llm_max_calls_per_5h, "llm_max_calls_per_day": s.llm_max_calls_per_day,
            "auto_submit": s.auto_submit, "auto_submit_sources": sorted(s.auto_submit_source_set),
            "browser_headless": s.browser_headless, "scheduler_enabled": s.scheduler_enabled,
            "data_dir": str(s.data_dir), "config_dir": str(s.config_dir),
        },
        "llm": {**provider_status(), "budget": budget_status(db)},
        "scheduler": scheduler.info(),
    }


@router.put("/search")
def put_search(body: SearchProfile):
    save_search_profile(body)
    return body.model_dump()


@router.put("/answer_bank")
def put_answer_bank(body: AnswerBank):
    save_answer_bank(body)
    return body.model_dump()


class CustomAnswer(BaseModel):
    q: str
    a: str


@router.post("/answer_bank/custom")
def add_custom_answer(body: CustomAnswer):
    """Save one answer typed on the review screen so the next form gets it automatically."""
    q, a = body.q.strip().rstrip("*: ").strip(), body.a.strip()
    if not q or not a:
        raise HTTPException(400, "question and answer are required")
    bank = load_answer_bank()
    bank.custom = [x for x in bank.custom if (x.get("q") or "").strip().lower() != q.lower()] + [{"q": q, "a": a}]
    save_answer_bank(bank)
    return bank.model_dump()


@router.get("/sources", response_model=list[SourceOut])
def get_sources(db: Session = Depends(get_session)):
    return _sources(db)


@router.put("/sources")
def put_sources(body: dict[str, bool], db: Session = Depends(get_session)):
    known = all_sources()
    for name, on in body.items():
        if name not in known:
            raise HTTPException(400, f"unknown source {name}")
        set_source_enabled(db, name, bool(on))
    return enabled_sources(db)


_VIA_SCHEDULE = ("schedule.", "apply.mode")    # these must go through PUT /settings/schedule (validated, rescheduled)


@router.put("/runtime")
def put_runtime(body: dict[str, Any], db: Session = Depends(get_session)):
    for k in body:
        if k not in DEFAULTS or k == "sources.enabled":
            raise HTTPException(400, f"unknown runtime setting {k}")
        if k.startswith(_VIA_SCHEDULE):
            raise HTTPException(400, f"{k} is changed through /settings/schedule")
    from ..llm.providers import PROVIDERS

    if "llm.provider" in body and body["llm.provider"] not in PROVIDERS:
        raise HTTPException(400, f"unknown AI provider {body['llm.provider']}; one of {', '.join(PROVIDERS)}")
    for k in ("llm.model", "llm.base_url"):
        if k in body and not isinstance(body[k], str):
            raise HTTPException(400, f"{k} must be text")
    if str(body.get("llm.base_url") or "").strip() and not str(body["llm.base_url"]).startswith(("http://", "https://")):
        raise HTTPException(400, "the server address must start with http:// or https://")
    for k, v in body.items():
        set_setting(db, k, v)
    return runtime_settings(db)


@router.get("/sites")
def get_sites():
    return load_sites()


@router.put("/sites")
def put_sites(body: list[SiteIn]):
    sites = [s.model_dump(exclude_none=True) for s in body]
    keys = [s["key"] for s in sites]
    if len(keys) != len(set(keys)):
        raise HTTPException(400, "duplicate site keys")
    save_sites(sites)
    return load_sites()


@router.post("/sites")
def add_site(body: SiteIn):
    sites = load_sites()
    if any(s["key"] == body.key for s in sites):
        raise HTTPException(409, "site key exists")
    sites.append(body.model_dump(exclude_none=True))
    save_sites(sites)
    return load_sites()


@router.delete("/sites/{key}")
def delete_site(key: str):
    sites = [s for s in load_sites() if s["key"] != key]
    save_sites(sites)
    return sites


@router.get("/schedule")
def get_schedule():
    return scheduler.info()


@router.put("/schedule")
def put_schedule(body: dict[str, Any]):
    """Partial update: {paused?, collect?: {enabled, days, time}, analyze?: {..., limit}, prepare?: {enabled, limit,
    min_fit}, apply_mode?}. Days are 0=Mon … 6=Sun."""
    try:
        return scheduler.configure(body)
    except (ValueError, TypeError) as e:
        raise HTTPException(400, str(e)) from e


@router.post("/schedule/plan/{plan}")
def put_plan(plan: str):
    try:
        return scheduler.apply_plan(plan)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/source-presets")
def source_presets(db: Session = Depends(get_session)):
    from ..sources.presets import list_presets

    return list_presets(db)


@router.post("/source-presets/{preset}")
def use_source_preset(preset: str, db: Session = Depends(get_session)):
    from ..sources.presets import apply_preset, list_presets

    try:
        apply_preset(db, preset)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return list_presets(db)


@router.get("/llm/models")
def llm_models():
    """Models the chosen AI provider offers (asks the provider's free model list; no AI call)."""
    from ..llm.client import provider_models

    return {"models": provider_models()}


@router.post("/llm/test")
def test_llm():
    """One tiny structured call, to check the AI provider end to end from the UI."""
    import time

    from ..llm.client import LLMError, run_llm

    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}, "model_says": {"type": "string"}},
              "required": ["ok", "model_says"]}
    t0 = time.monotonic()
    try:
        out = run_llm("Reply with ok=true and model_says set to a five-word greeting.", purpose="test", schema=schema,
                      timeout_s=90, enforce_budget=False)
    except LLMError as e:
        raise HTTPException(502, str(e)) from e
    return {"ok": bool(out.get("ok")), "reply": out.get("model_says"), "seconds": round(time.monotonic() - t0, 1)}
