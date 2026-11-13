"""Fill (and optionally submit) one application in the browser."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ... import cancel
from ...browser import dismiss_cookie_banners, launch_context, looks_blocked, new_page
from ...config import get_settings
from ...llm.client import run_llm
from ...llm.prompts import FORM_SCHEMA, FORM_SYSTEM, build_form_prompt
from ...models import Application, ApplicationStatus, JobStatus, Profile, Run, mark_submitted, utcnow
from ...settings_store import get_setting
from ...sources.ats_detect import apply_url_for
from .base import execute_plan, find_submit, inspect_form, page_outcome, reveal_form


def _dedupe_questions(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for q in items:
        key = re.sub(r"\b(required|optional)\b", " ", (q or "").lower())
        key = re.sub(r"[^a-z0-9]+", " ", key).strip()
        if key and key not in seen:
            seen.add(key)
            out.append(q.strip())
    return out


class ApplicationLocked(ValueError):
    """The application was sent, is being sent, or was withdrawn: it must never be filled or submitted again."""


_LOCKED = (ApplicationStatus.SUBMITTING, ApplicationStatus.SUBMITTED, ApplicationStatus.WITHDRAWN)


def check_open(app: Application) -> None:
    """Raise ApplicationLocked unless the application may still be filled or submitted."""
    if app.submitted_at is not None:
        raise ApplicationLocked("submit was already clicked for this application; check the ATS. If it did not go "
                                "through, use \"It didn't go through\" on the application first")
    if app.status in _LOCKED:
        raise ApplicationLocked(f"the application is {app.status.replace('_', ' ')}")


def apply_application(db: Session, app_id: int, submit: bool | None = None,
                      log: Callable[[str], None] | None = None, only_approved: bool = False) -> Application:
    """submit=None → follow settings (auto_submit + whitelist); True → submit; False → fill & screenshot only.

    only_approved: the batch path; the application must still be APPROVED when its turn comes.
    """
    s = get_settings()
    app = db.get(Application, app_id)
    if app is None:
        raise ValueError(f"application {app_id} not found")
    db.refresh(app)           # the UI or the CLI may have changed it since this session loaded it
    check_open(app)
    job = app.job
    if app.method == "manual" or not (job.apply_url or job.url):
        app.status = ApplicationStatus.MANUAL
        app.log = (app.log or "") + "\nno automatable form (apply by hand with the prepared material)"
        db.commit()
        return app

    if submit is None:
        submit = s.auto_submit and (app.ats_type in s.auto_submit_source_set)
    before = app.status
    # Claim it in one statement, so two sessions can never fill or submit the same application, and one that was
    # withdrawn, sent by hand or un-approved a moment ago is left alone.
    cond = [Application.id == app.id, Application.submitted_at.is_(None), Application.status.notin_(_LOCKED)]
    if only_approved:
        cond.append(Application.status == ApplicationStatus.APPROVED)
    claimed = db.execute(update(Application).where(*cond)
                         .values(status=ApplicationStatus.SUBMITTING, updated_at=utcnow(), worker_pid=os.getpid())).rowcount
    db.commit()
    if claimed != 1:
        raise ApplicationLocked("the application changed while it was waiting (sent, withdrawn or no longer approved)")
    db.refresh(app)
    lines: list[str] = [(app.log or "").strip()] if app.log else []

    def _log(m: str) -> None:
        line = f"{datetime.now():%H:%M:%S} {m}"          # local time, like the rest of the UI
        lines.append(line)
        if log:
            log(line)

    run = Run(kind="apply", source=app.ats_type or "generic", status="running", stats={"application_id": app.id})
    db.add(run)
    db.commit()

    profile = (db.get(Profile, app.resume_id) if app.resume_id else None) or db.get(Profile, 1)
    url = apply_url_for(app.ats_type, job.apply_url or job.url)
    _log(f"open {url} (submit={submit})")
    outcome = "unknown"
    snippet = ""
    clicked = False
    try:
        with launch_context() as bctx:
            page = new_page(bctx)
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(2500)
            dismiss_cookie_banners(page)
            if looks_blocked(page):
                raise RuntimeError("bot check / login wall on the application page; sign in once with browser-login")
            scope, fields = inspect_form(page)
            if len([f for f in fields if f["type"] != "checkbox"]) < 2 and reveal_form(page):
                _log("clicked Apply to reveal the form")
                scope, fields = inspect_form(page)
            if len(fields) < 2:
                raise RuntimeError("no application form found on the page")
            _log(f"{len(fields)} form fields found" + ("" if scope == page.main_frame else " (inside an embedded frame)"))

            answers = dict(app.answers or {})
            profile_summary = "\n".join(x for x in [
                profile.headline if profile else None, profile.summary if profile else None,
                ("Skills: " + ", ".join(profile.skills)) if profile and profile.skills else None,
            ] if x)
            plan_res = run_llm(build_form_prompt(fields, answers, profile_summary, app.cover_letter,
                                                    {"company_name": job.company_name, "title": job.title}),
                                  purpose="form", schema=FORM_SCHEMA, system=FORM_SYSTEM, db=db)
            plan = plan_res.get("plan", [])
            app.form_plan = plan
            unanswered = list(plan_res.get("unanswered", []))
            _log(f"plan: {len(plan)} actions, {len(unanswered)} unanswered")

            result = execute_plan(scope, fields, plan, app.resume_path or (profile.resume_path if profile else None),
                                  pause_ms=int(s.apply_pause_s * 300))
            app.unanswered = _dedupe_questions(unanswered + result.skipped_required)
            _log(f"filled {len(result.filled)}, failed {len(result.failed)}, required-but-empty {len(result.skipped_required)}")
            for f in result.failed:
                _log(f"  ! {f['field']}: {f['error']}")

            shot = s.screenshots_dir / f"app-{app.id}-{utcnow():%Y%m%d-%H%M%S}.png"
            try:
                page.screenshot(path=str(shot), full_page=True)
                app.screenshot_path = str(shot)
            except Exception:
                pass

            # Anything the agent could not answer truthfully blocks the click: required fields left empty and the
            # questions the model listed as unanswered.
            if submit and not app.unanswered:
                btn = find_submit(scope)
                if btn is None:
                    raise RuntimeError("could not find the submit button")
                btn.click(timeout=8000)
                clicked = True
                # Persist the click immediately so a crash or an unclear outcome can never lead to a second submit.
                app.submitted_at = utcnow()
                app.confirmation = f"submit clicked at {app.submitted_at:%Y-%m-%d %H:%M:%S} UTC; outcome not verified yet"
                db.commit()
                _log("clicked submit")
                try:
                    page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    page.wait_for_timeout(4000)
                outcome, snippet = page_outcome(scope if scope.page == page and not scope.is_detached() else page.main_frame)
                shot2 = s.screenshots_dir / f"app-{app.id}-after-submit.png"
                try:
                    page.screenshot(path=str(shot2), full_page=True)
                    app.screenshot_path = str(shot2)
                except Exception:
                    pass
                _log(f"outcome: {outcome} {snippet[:120]}")
            elif submit:
                _log("not submitted: questions without a truthful answer: " + "; ".join(app.unanswered))
    except Exception as e:
        app.status = ApplicationStatus.FAILED if (submit and not clicked) else ApplicationStatus.NEEDS_REVIEW
        app.error = f"{type(e).__name__}: {e}"
        if clicked:
            app.error += " (after the submit click; verify in the ATS before resubmitting)"
        _log("! " + app.error)
        app.log = "\n".join(lines)[-20000:]
        run.status, run.error, run.finished_at, run.log = "error", app.error, utcnow(), app.log
        db.commit()
        return app

    app.error = None
    if clicked and outcome == "submitted":
        app.status = ApplicationStatus.SUBMITTED
        app.confirmation = snippet
        job.status = JobStatus.APPLIED
        mark_submitted(app, int(get_setting(db, "applications.follow_up_days") or 10))
    elif clicked and outcome == "error":
        # Error text on the page is only a guess (a job description can say "must be"), so submitted_at stays set:
        # nothing is sent again until the user checks and says it did not go through.
        app.status = ApplicationStatus.NEEDS_REVIEW
        app.error = f"the page may show an error after the submit click: {snippet}. Check the ATS or the screenshot."
    elif clicked:   # unknown outcome
        if not app.unanswered:
            app.status = ApplicationStatus.SUBMITTED
            app.confirmation = "submitted (no confirmation text detected; check the screenshot)"
            job.status = JobStatus.APPLIED
            mark_submitted(app, int(get_setting(db, "applications.follow_up_days") or 10))
        else:
            app.status = ApplicationStatus.NEEDS_REVIEW
            app.error = "submit was clicked but no confirmation text was found; check the ATS/screenshot before resubmitting"
    elif before == ApplicationStatus.APPROVED and not app.unanswered:
        app.status = ApplicationStatus.APPROVED            # a check-only fill keeps the user's approval
    else:
        app.status = ApplicationStatus.NEEDS_REVIEW
    app.log = "\n".join(lines)[-20000:]
    run.status = "ok" if app.status == ApplicationStatus.SUBMITTED or not submit else "partial"
    run.finished_at = utcnow()
    run.log = app.log
    run.stats = {"application_id": app.id, "status": app.status, "unanswered": len(app.unanswered or []),
                 "plan": json.dumps(app.form_plan or [])[:50]}
    db.commit()
    return app


def submit_approved(db: Session, log: Callable[[str], None] | None = None, limit: int = 5,
                    ats_only: set[str] | None = None) -> dict:
    """Submit approved applications. ats_only: the automatic path passes JOBAGENT_AUTO_SUBMIT_SOURCES."""
    q = select(Application.id).where(Application.status == ApplicationStatus.APPROVED, Application.submitted_at.is_(None))
    if ats_only is not None:
        q = q.where(Application.ats_type.in_(ats_only))
    ids = db.scalars(q.order_by(Application.updated_at).limit(limit)).all()
    stats = {"attempted": 0, "submitted": 0, "needs_review": 0, "failed": 0, "skipped": 0}
    for app_id in ids:
        if cancel.requested():          # only between applications: a form is never abandoned half-filled
            break
        try:
            a = apply_application(db, app_id, submit=True, log=log, only_approved=True)
        except ApplicationLocked as e:
            stats["skipped"] += 1
            if log:
                log(f"  skipped #{app_id}: {e}")
            continue
        stats["attempted"] += 1
        key = {"submitted": "submitted", "needs_review": "needs_review"}.get(a.status, "failed")
        stats[key] += 1
    return stats
