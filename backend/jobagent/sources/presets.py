"""Starting sets of sources for the setup wizard ("India + remote", "Remote worldwide", "India only").

A preset only switches sources that are on by default. Sources that ship off (login walls, or terms that forbid
automated reading such as Indeed or Glassdoor) are never turned on by a preset and never turned off if the user
opted in to them.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ..settings_store import enabled_sources, set_source_enabled
from .base import all_sources

_CORE = {"greenhouse", "lever", "ashby", "workable", "smartrecruiters", "company_careers"}
_INDIA = {"hasjob", "geektrust", "ziprecruiter_in", "linkedin", "site_builtin", "site_cutshort", "site_foundit",
          "site_hirist", "site_timesjobs", "site_weekday", "site_wellfound"}
_REMOTE = {"arc", "eighty_thousand_hours", "himalayas", "hn_hiring", "jobicy", "jobspresso", "justremote", "nodesk",
           "remoteok", "remotive", "we_work_remotely", "working_nomads", "site_aijobs_ai", "site_dynamite_jobs",
           "site_startup_jobs", "site_wellfound", "site_yc_startups"}

PRESETS: dict[str, dict[str, Any]] = {
    "india_remote": {"name": "India + remote", "desc": "Indian boards, company career pages and remote boards open to India.",
                     "sources": _CORE | _INDIA | _REMOTE},
    "remote": {"name": "Remote worldwide", "desc": "Remote boards and company pages that hire across countries.",
               "sources": _CORE | _REMOTE},
    "india": {"name": "India only", "desc": "Indian boards and company career pages, no remote-only boards.",
              "sources": _CORE | _INDIA},
}


def list_presets(db: Session) -> list[dict[str, Any]]:
    known = all_sources()
    enabled = enabled_sources(db)
    out = []
    for pid, p in PRESETS.items():
        names = [n for n in p["sources"] if n in known]
        target = {n for n, cls in known.items() if cls.default_enabled and n in names}
        current = {n for n, cls in known.items() if cls.default_enabled and enabled.get(n)}
        out.append({"id": pid, "name": p["name"], "desc": p["desc"], "count": len(names), "active": target == current})
    return out


def apply_preset(db: Session, preset_id: str) -> dict[str, bool]:
    if preset_id not in PRESETS:
        raise ValueError(f"unknown preset {preset_id}")
    wanted = PRESETS[preset_id]["sources"]
    for name, cls in all_sources().items():
        if cls.default_enabled:
            set_source_enabled(db, name, name in wanted)
    return enabled_sources(db)
