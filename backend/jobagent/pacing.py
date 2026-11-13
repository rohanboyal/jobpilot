"""Careful pace for sites read with the user's own account.

A site the user signed in to sees every crawl as that account, so it gets unhurried visits: random gaps between pages,
a longer break now and then, few job pages per run, one automatic read a day, and a rest once the site refuses a visit.
This only lowers how much and how fast we read; it does not disguise the browser. Every other source keeps its normal
speed, and form filling is never paced (visits are only counted inside a crawl).
"""

from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import cancel
from .health import was_refused, was_skipped
from .models import Job, Run, utcnow
from .settings_store import get_setting, set_setting

GAP_S = (6.0, 18.0)         # between two pages
BREAK_S = (45.0, 120.0)     # a longer break ...
BREAK_EVERY = (8, 14)       # ... after this many pages
START_S = (60.0, 240.0)     # before an automatic read, so a site isn't opened the same second every day
DETAIL_PAGES = 25           # job pages opened per run
READ_EVERY_H = 20           # automatic reads of one site
REST_H, REST_MAX_H = 24, 7 * 24   # after a refusal: a day, then 2, 4 ... up to a week while it keeps refusing


class SiteRefused(RuntimeError):
    """The site turned a visit away. No further page of it is opened in this run."""


@dataclass
class Visits:
    log: Callable[[str], None]
    count: int = 0
    next_break: int = 0
    refused: str | None = None


_local = threading.local()


def _current() -> Visits | None:
    return getattr(_local, "visits", None)


def active() -> bool:
    return _current() is not None


def begin(log: Callable[[str], None]) -> Visits:
    _local.visits = Visits(log=log, next_break=random.randint(*BREAK_EVERY))
    return _local.visits


def end() -> None:
    _local.visits = None


def note_refused(reason: str) -> None:
    v = _current()
    if v and not v.refused:
        v.refused = reason


def _wait(seconds: float, sleep: Callable[[float], Any] = time.sleep) -> None:
    deadline = time.monotonic() + seconds
    while (left := deadline - time.monotonic()) > 0 and not cancel.requested():
        sleep(min(left, 0.5))


def wait_to_start(log: Callable[[str], None]) -> None:
    seconds = random.uniform(*START_S)
    log(f"careful pace: starting in {seconds:.0f}s")
    _wait(seconds)


def _take_turn(v: Visits, page: Any) -> None:
    if v.refused:
        raise SiteRefused(v.refused)
    if v.count:
        seconds = random.uniform(*GAP_S)
        if v.count >= v.next_break:
            seconds = random.uniform(*BREAK_S)
            v.next_break = v.count + random.randint(*BREAK_EVERY)
            v.log(f"careful pace: a {seconds:.0f}s break")
        _wait(seconds, lambda s: page.wait_for_timeout(s * 1000))
    if cancel.requested():
        raise RuntimeError("stopped by user")
    v.count += 1


def attach(page: Any) -> None:
    """Make page.goto wait its turn, and stop opening pages once the site has refused one."""
    goto = page.goto

    def paced_goto(url: str, **kw: Any) -> Any:
        v = _current()
        if v is None:
            return goto(url, **kw)
        _take_turn(v, page)
        resp = goto(url, **kw)
        if resp is not None and resp.status in (403, 429):
            v.refused = f"HTTP {resp.status}"
            raise SiteRefused(f"HTTP {resp.status} for {url}")
        return resp

    page.goto = paced_goto


def signed_in_sites(db: Session) -> set[str]:
    return set(get_setting(db, "browser.signed_in") or [])


def mark_signed_in(db: Session, name: str, on: bool = True) -> None:
    """Set by the Sign in button; "Not signed in" on the Sources page clears it."""
    sites = signed_in_sites(db)
    sites.add(name) if on else sites.discard(name)
    set_setting(db, "browser.signed_in", sorted(sites))


def known_urls(db: Session, name: str) -> set[str]:
    """Job pages already read: no reason to open them again."""
    return set(db.scalars(select(Job.url).where(Job.source == name, func.length(Job.description) > 200)).all())


def _local_time(t: datetime) -> str:
    return f"{t.replace(tzinfo=UTC).astimezone():%d %b %H:%M}"


def skip_reason(db: Session, name: str, profiles: list[int] | None = None) -> str | None:
    """Why an automatic run should leave this signed-in site alone. A run the user asks for by name ignores it.
    profiles: what this run searches for; a site is searched for each profile once a day."""
    rows = db.scalars(select(Run).where(Run.kind == "crawl", Run.source == name, Run.finished_at.is_not(None))
                      .order_by(Run.started_at.desc()).limit(30)).all()
    real = [r for r in rows if not was_skipped(r)]
    strikes = 0
    for r in real:
        if not was_refused(r):
            break
        strikes += 1
    if strikes:
        until = real[0].finished_at + timedelta(hours=min(REST_H * 2 ** (strikes - 1), REST_MAX_H))
        if until > utcnow():
            return f"skipped: resting until {_local_time(until)} because the site refused the last visit"
    if strikes == 0:
        covered: set[int] = set()
        for r in real:
            if utcnow() - r.finished_at >= timedelta(hours=READ_EVERY_H):
                break
            stats = r.stats or {}
            if stats.get("fetched") and not stats.get("cancelled"):
                if stats.get("profiles") is None:      # recorded before runs covered some profiles: it searched all
                    return f"skipped: already read in the last {READ_EVERY_H} hours"
                covered |= set(stats["profiles"])
        if covered and set(profiles or []) <= covered:
            return f"skipped: already read for these profiles in the last {READ_EVERY_H} hours"
    return None
