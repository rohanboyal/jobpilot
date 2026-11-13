"""Source adapters. Import-side effect registers each adapter."""

from __future__ import annotations

import importlib

_MODULES = [
    "greenhouse", "lever", "ashby", "workable", "smartrecruiters",
    "remotive", "remoteok", "hn_hiring", "adzuna", "jooble",
    "linkedin", "indeed", "naukri", "shine", "company_careers",
    "ziprecruiter_in", "hasjob", "geektrust", "himalayas", "working_nomads", "jobspresso", "nodesk",
    "we_work_remotely", "jobicy", "arbeitnow", "arc", "crossover", "dice", "eighty_thousand_hours", "justremote", "jobgether",
    "wearedevelopers", "reed", "themuse", "levelsfyi",
    "generic_sites",
]
_loaded = False


def load_all() -> None:
    global _loaded
    if _loaded:
        return
    for m in _MODULES:
        importlib.import_module(f"{__name__}.{m}")
    _loaded = True
