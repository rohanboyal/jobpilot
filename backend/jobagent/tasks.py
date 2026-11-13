"""Background task runner: pipeline stages run in threads; the UI polls their status."""

from __future__ import annotations

import threading
import traceback
import uuid
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from . import cancel
from .db import session_scope

_lock = threading.Lock()
_tasks: dict[str, dict[str, Any]] = {}
_running_kinds: set[str] = set()
_ORDER: deque[str] = deque(maxlen=50)
# tasks in the same group never run at the same time (they all write the jobs table heavily)
_GROUPS = {"crawl": "pipeline", "cycle": "pipeline", "score": "pipeline", "prepare": "pipeline", "apply": "pipeline",
           "collect": "pipeline", "analyze": "pipeline"}


class TaskBusy(RuntimeError):
    pass


def _new_task(kind: str, label: str) -> dict[str, Any]:
    t = {"id": uuid.uuid4().hex[:10], "kind": kind, "label": label, "status": "running",
         "started_at": datetime.now(UTC).replace(tzinfo=None).isoformat(), "finished_at": None, "result": None, "error": None,
         "log": deque(maxlen=400), "stop": threading.Event()}
    _tasks[t["id"]] = t
    _ORDER.append(t["id"])
    for old in list(_tasks):
        if old not in _ORDER:
            _tasks.pop(old, None)
    return t


def start(kind: str, label: str, fn: Callable[..., Any], *args: Any, exclusive: bool = True, **kwargs: Any) -> dict:
    """Run fn(db, *args, log=..., **kwargs) in a thread. One task per `kind` at a time when exclusive."""
    group = _GROUPS.get(kind, kind)
    with _lock:
        if exclusive and group in _running_kinds:
            raise TaskBusy(f"a '{group}' task is already running; wait for it to finish")
        t = _new_task(kind, label)
        if exclusive:
            _running_kinds.add(group)

    def _log(msg: str) -> None:
        t["log"].append(msg)

    def _run() -> None:
        cancel.bind(t["stop"])
        try:
            with session_scope() as db:
                t["result"] = fn(db, *args, log=_log, **kwargs)
            t["status"] = "cancelled" if t["stop"].is_set() else "ok"
        except Exception as e:
            t["status"] = "error"
            t["error"] = f"{type(e).__name__}: {e}"
            _log(traceback.format_exc()[-2000:])
        finally:
            cancel.bind(None)
            t["finished_at"] = datetime.now(UTC).replace(tzinfo=None).isoformat()
            with _lock:
                _running_kinds.discard(group)

    threading.Thread(target=_run, name=f"task-{kind}", daemon=True).start()
    return public(t)


def public(t: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in t.items() if k not in ("log", "stop")}
    out["stopping"] = t["status"] == "running" and t["stop"].is_set()
    out["log_tail"] = list(t["log"])[-40:]
    return out


def list_tasks() -> list[dict[str, Any]]:
    return [public(_tasks[i]) for i in reversed(_ORDER) if i in _tasks]


def get_task(task_id: str) -> dict[str, Any] | None:
    t = _tasks.get(task_id)
    return public(t) if t else None


def running() -> list[str]:
    return sorted(_running_kinds)


def stop(task_id: str | None = None) -> list[str]:
    """Ask running tasks (one, or all when task_id is None) to wind down after the current unit of work."""
    stopped = []
    for tid, t in list(_tasks.items()):
        if t["status"] == "running" and (task_id is None or tid == task_id):
            t["stop"].set()
            t["log"].append("stop requested: finishing the current step, then stopping")
            stopped.append(tid)
    return stopped


# ---------------------------------------------------------------------------
# Composite jobs
# ---------------------------------------------------------------------------


def _passes(db, profile_ids: list[int] | None, one_by_one: bool) -> list[list[int] | None]:
    """The profiles each pass covers: one pass for the chosen profiles (None = every enabled one), or one per profile."""
    if not one_by_one:
        return [profile_ids]
    from .profiles import enabled_profiles

    return [[pid] for pid, _ in enabled_profiles(db, profile_ids)]


def _heading(db, stage: str, ids: list[int] | None) -> str:
    from .profiles import names

    return f"## {stage}" + ("" if ids is None else f" · {names(db, ids)}")


def _add(total: dict[str, Any], part: dict[str, Any]) -> dict[str, Any]:
    """Add one pass's stats to the run's totals ('remaining' and messages keep the latest value)."""
    for k, v in part.items():
        if isinstance(v, int) and not isinstance(v, bool) and k != "remaining":
            total[k] = total.get(k, 0) + v
        elif isinstance(v, dict):
            _add(total.setdefault(k, {}), v)
        elif v or k not in total:
            total[k] = v
    return total


def _collect_pass(db, log: Callable[[str], None], sources: list[str] | None, ids: list[int] | None,
                  later_pass: bool) -> dict[str, Any]:
    from .pipeline.ingest import crawl_all
    from .pipeline.prefilter import prefilter_new

    log(_heading(db, "collect", ids))
    # Company boards are read whole whatever the search, so a second pass would only fetch the same jobs again.
    runs = crawl_all(db, only=sources, log=log, profile_ids=ids, skip_kinds=("ats",) if later_pass else ())
    out: dict[str, Any] = {"crawl": {r.source: {"status": r.status, **(r.stats or {})} for r in runs}}
    log("## prefilter")
    out["prefilter"] = prefilter_new(db)      # cheap and local: always finish it so crawled jobs are not left as 'new'
    log(str(out["prefilter"]))
    return out


def _expire(db, log: Callable[[str], None], out: dict[str, Any]) -> None:
    from .pipeline.ingest import expire_stale

    if not cancel.requested():
        out["expired_stale"] = expire_stale(db)
        if out["expired_stale"]:
            log(f"expired {out['expired_stale']} board/site jobs no crawl has seen for a while")


def _analyze_pass(db, log: Callable[[str], None], limit: int | None, ids: list[int] | None) -> dict[str, Any]:
    from .pipeline.prepare import prepare_shortlisted
    from .pipeline.scoring import score_queued
    from .settings_store import get_setting

    out: dict[str, Any] = {}
    log(_heading(db, "analyze", ids))
    out["score"] = score_queued(db, limit=limit, log=log, profile_ids=ids)
    if (get_setting(db, "schedule.prepare") or {}).get("enabled", True) and not cancel.requested():
        log("## prepare")
        out["prepare"] = prepare_shortlisted(db, log=log, profile_ids=ids)
    return out


def _submit_approved(db, log: Callable[[str], None], out: dict[str, Any]) -> None:
    from .config import get_settings
    from .pipeline.apply.runner import submit_approved
    from .settings_store import get_setting

    if cancel.requested():
        log("stopped")
        return
    if get_setting(db, "apply.mode") == "auto" and get_settings().auto_submit:
        log("## submit approved")
        out["apply"] = submit_approved(db, log=log, ats_only=get_settings().auto_submit_source_set)


def collect_stage(db, log: Callable[[str], None], sources: list[str] | None = None,
                  profile_ids: list[int] | None = None, one_by_one: bool = False) -> dict[str, Any]:
    """Stage 1: crawl every enabled source, dedupe, run the free prefilter. No AI except pages without selectors.
    profile_ids: search for these profiles only (None = every enabled one); one_by_one: a separate pass for each."""
    out: dict[str, Any] = {}
    for n, ids in enumerate(_passes(db, profile_ids, one_by_one)):
        if cancel.requested():
            break
        _add(out, _collect_pass(db, log, sources, ids, later_pass=n > 0))
    _expire(db, log, out)
    return out


def analyze_stage(db, log: Callable[[str], None], limit: int | None = None,
                  profile_ids: list[int] | None = None, one_by_one: bool = False) -> dict[str, Any]:
    """Stage 2 + 3 (+ 4 when auto-submit is on): score the best new matches, draft for the top ones, submit approved.
    One after another, each profile gets its own Analyze limit."""
    out: dict[str, Any] = {}
    for ids in _passes(db, profile_ids, one_by_one):
        if cancel.requested():
            break
        _add(out, _analyze_pass(db, log, limit, ids))
        if (out.get("score") or {}).get("stopped"):
            break                                  # out of AI calls (or too many errors): the next profile would be too
    _submit_approved(db, log, out)
    return out


def full_cycle(db, log: Callable[[str], None], sources: list[str] | None = None,
               profile_ids: list[int] | None = None, one_by_one: bool = False) -> dict[str, Any]:
    """Run now: collect, then analyze/prepare (and submit approved when auto-submit is on). One after another, each
    profile is collected and analyzed before the next one starts."""
    out: dict[str, Any] = {}
    for n, ids in enumerate(_passes(db, profile_ids, one_by_one)):
        _add(out, _collect_pass(db, log, sources, ids, later_pass=n > 0))
        if cancel.requested():
            log("stopped before analyzing")
            break
        _add(out, _analyze_pass(db, log, None, ids))
        if cancel.requested() or (out.get("score") or {}).get("stopped"):
            break
    _expire(db, log, out)
    _submit_approved(db, log, out)
    return out
