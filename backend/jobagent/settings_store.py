"""Runtime toggles that live in the database (editable from the UI), layered over code defaults."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from .models import Setting

DEFAULTS: dict[str, Any] = {
    "sources.enabled": {},                 # overrides of each source's default_enabled
    # Stage schedule. Days are 0=Mon … 6=Sun, times are local HH:MM. Nothing runs on its own while paused.
    "schedule.paused": True,               # off until the user picks a plan in Setup or turns it on
    "schedule.collect": {"enabled": True, "days": [0, 1, 2, 3, 4, 5, 6], "time": "08:00"},
    "schedule.analyze": {"enabled": True, "days": [0, 3], "time": "09:00", "limit": 30},
    "schedule.prepare": {"enabled": True, "limit": 6, "min_fit": 75},   # runs right after each Analyze
    "apply.mode": "approve",               # approve | auto (needs JOBAGENT_AUTO_SUBMIT) | manual
    "pipeline.min_trust_for_shortlist": 40,
    "jobs.saved_views": [],
    "jobs.keep_days": 30,                  # Jobs lists and Analyze skip jobs found longer ago (applied ones always stay)
    "today.recent_days": 7,                # the Today page shows jobs found in the last N days
    "jobs.stale_after_days": 21,           # board/site jobs not seen by any crawl for this long are expired
    "applications.follow_up_days": 10,     # remind to follow up this long after applying                # [{"id", "name", "filters": {...}}] saved from the Jobs page
    "setup.completed": False,
    "browser.signed_in": [],               # sources the user signed in to: read at the careful pace (pacing.py)
    "browser.channel": "",                 # "" = Playwright's own Chromium; "chrome" / "msedge" = that installed app,
                                           # picked by the browser the user clicks Sign in from (browser.py)
    "llm.provider": "codex",               # codex | claude | openai | gemini | anthropic | ollama (llm/providers.py)
    "llm.model": "",                       # empty = the provider's default (Codex / Claude Code / Ollama)
    "llm.base_url": "https://api.openai.com/v1",   # for "openai": any OpenAI-compatible server
    "llm.fallback_enabled": False,         # use the local Ollama model when the main AI hits a limit
    "llm.fallback_model": "qwen3.5:4b",
    "llm.fallback_purposes": ["score", "extract"],   # never cover letters or form filling by default
}


def get_setting(db: Session, key: str, default: Any = None) -> Any:
    row = db.get(Setting, key)
    if row is None:
        return DEFAULTS.get(key, default)
    return row.value


def set_setting(db: Session, key: str, value: Any) -> None:
    row = db.get(Setting, key)
    if row is None:
        db.add(Setting(key=key, value=value))
    else:
        row.value = value
    db.commit()


def runtime_settings(db: Session) -> dict[str, Any]:
    return {k: get_setting(db, k) for k in DEFAULTS if k != "sources.enabled"}


def enabled_sources(db: Session) -> dict[str, bool]:
    from .sources.base import all_sources

    overrides = get_setting(db, "sources.enabled") or {}
    return {name: bool(overrides.get(name, cls.default_enabled)) for name, cls in all_sources().items()}


def set_source_enabled(db: Session, name: str, enabled: bool) -> None:
    overrides = dict(get_setting(db, "sources.enabled") or {})
    overrides[name] = enabled
    set_setting(db, "sources.enabled", overrides)
