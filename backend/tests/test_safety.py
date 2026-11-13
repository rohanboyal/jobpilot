"""Rules that must survive changes: nothing is sent twice or behind the user's back, sent and withdrawn applications
are never touched again, and what the user decided survives background work."""

from __future__ import annotations

import pytest

from jobagent.db import session_scope
from jobagent.models import Application, ApplicationStatus, Job, JobStatus, utcnow


def _make(fp: str, job_status: str = JobStatus.APPLYING, app_status: str | None = ApplicationStatus.NEEDS_REVIEW,
          **app_kw) -> tuple[int, int | None]:
    with session_scope() as db:
        job = Job(fingerprint=fp, source="greenhouse", company_name="Acme", title="Backend Engineer",
                  url=f"https://boards.greenhouse.io/acme/jobs/{fp}", status=job_status, fit_score=82)
        db.add(job)
        db.flush()
        app_id = None
        if app_status:
            app = Application(job_id=job.id, status=app_status, method="browser", ats_type="greenhouse", **app_kw)
            db.add(app)
            db.flush()
            app_id = app.id
        db.commit()
        return job.id, app_id


def _app(app_id: int) -> Application:
    with session_scope() as db:
        return db.get(Application, app_id)


@pytest.mark.parametrize("status,clicked", [(ApplicationStatus.SUBMITTED, True), (ApplicationStatus.WITHDRAWN, False),
                                            (ApplicationStatus.NEEDS_REVIEW, True)])
def test_sent_withdrawn_or_clicked_applications_are_never_filled_again(client, status, clicked):
    from jobagent.pipeline.apply.runner import ApplicationLocked, apply_application

    _, app_id = _make(f"fp-locked-{status}-{clicked}", app_status=status, submitted_at=utcnow() if clicked else None)
    with session_scope() as db, pytest.raises(ApplicationLocked):
        apply_application(db, app_id, submit=True)
    assert _app(app_id).status == status                        # untouched, not moved back to needs_review
    assert client.post(f"/api/applications/{app_id}/fill").status_code == 409
    assert client.post(f"/api/applications/{app_id}/submit").status_code == 409


def test_a_change_made_elsewhere_is_seen_before_submitting():
    from jobagent.pipeline.apply.runner import ApplicationLocked, apply_application

    _, app_id = _make("fp-stale", app_status=ApplicationStatus.APPROVED)
    with session_scope() as batch:
        batch.get(Application, app_id)                          # the batch has loaded it ...
        with session_scope() as ui:                             # ... then the user withdraws it in the UI
            ui.get(Application, app_id).status = ApplicationStatus.WITHDRAWN
            ui.commit()
        with pytest.raises(ApplicationLocked):
            apply_application(batch, app_id, submit=True, only_approved=True)
    assert _app(app_id).status == ApplicationStatus.WITHDRAWN


def test_auto_submit_only_touches_allowed_ats():
    from jobagent.pipeline.apply.runner import submit_approved

    _, app_id = _make("fp-not-allowed", app_status=ApplicationStatus.APPROVED)
    with session_scope() as db:
        db.get(Application, app_id).ats_type = None             # a generic site, not a whitelisted ATS
        db.commit()
        stats = submit_approved(db, ats_only={"greenhouse", "lever", "ashby"}, limit=50)
    assert stats["attempted"] == 0 and _app(app_id).status == ApplicationStatus.APPROVED


def test_unclear_submit_stays_locked_until_the_user_says_it_failed(client):
    _, app_id = _make("fp-unclear", app_status=ApplicationStatus.NEEDS_REVIEW, submitted_at=utcnow())
    assert client.patch(f"/api/applications/{app_id}", json={"status": "withdrawn"}).status_code == 200
    assert client.patch(f"/api/applications/{app_id}", json={"clear_submit_click": True}).status_code == 409
    _, app_id = _make("fp-unclear2", app_status=ApplicationStatus.NEEDS_REVIEW, submitted_at=utcnow())
    r = client.patch(f"/api/applications/{app_id}", json={"clear_submit_click": True})
    assert r.status_code == 200 and r.json()["submitted_at"] is None


def test_a_submitted_application_cannot_be_moved_back(client):
    _, app_id = _make("fp-sent", job_status=JobStatus.APPLIED, app_status=ApplicationStatus.SUBMITTED,
                      submitted_at=utcnow())
    assert client.patch(f"/api/applications/{app_id}", json={"status": "needs_review"}).status_code == 409
    assert _app(app_id).status == ApplicationStatus.SUBMITTED


def test_reprepare_refuses_sent_and_keeps_typed_answers(client, monkeypatch):

    job_id, _ = _make("fp-sent-prep", job_status=JobStatus.APPLIED, app_status=ApplicationStatus.SUBMITTED,
                      submitted_at=utcnow())
    assert client.post(f"/api/jobs/{job_id}/prepare?force=true").status_code == 409

    job_id, app_id = _make("fp-reprep", app_status=ApplicationStatus.APPROVED,
                           answers={"What is your notice period?": "30 days", "why_this_role": "typed by me"})
    r = client.post(f"/api/jobs/{job_id}/prepare?force=true&cover=never")
    assert r.status_code == 200
    a = r.json()
    assert a["answers"]["What is your notice period?"] == "30 days" and a["answers"]["why_this_role"] == "typed by me"
    assert a["status"] == "needs_review" and a["id"] == app_id


def test_withdrawn_jobs_are_not_drafted_again_automatically(monkeypatch):
    from jobagent.pipeline import prepare

    calls = []
    monkeypatch.setattr(prepare, "run_llm", lambda *a, **k: calls.append(1) or {"cover_letter": "x", "short_pitch": "y"})
    _make("fp-withdrawn-job", job_status=JobStatus.SHORTLISTED, app_status=ApplicationStatus.WITHDRAWN)
    with session_scope() as db:
        before = db.query(Application).count()
        prepare.prepare_shortlisted(db, limit=50)
        assert db.query(Application).filter(Application.job.has(fingerprint="fp-withdrawn-job")).count() == 1
        assert db.query(Application).count() >= before


def test_status_changes_never_undo_an_application(client):
    job_id, _ = _make("fp-status", job_status=JobStatus.APPLIED, app_status=ApplicationStatus.SUBMITTED,
                      submitted_at=utcnow())
    assert client.post(f"/api/jobs/{job_id}/status", json={"status": "queued"}).status_code == 409
    r = client.post("/api/jobs/bulk", json={"ids": [job_id], "action": "requeue"}).json()
    assert r == {"updated": 0, "skipped": 1}
    with session_scope() as db:
        assert db.get(Job, job_id).status == JobStatus.APPLIED


def test_not_interested_survives_a_score_that_finishes_later(monkeypatch):
    from jobagent.pipeline import scoring

    job_id, _ = _make("fp-midscore", job_status=JobStatus.QUEUED, app_status=None)

    def slow_ai(*a, **k):                     # while the model works, the user marks the job not interested
        with session_scope() as ui:
            ui.get(Job, job_id).status = JobStatus.REJECTED
            ui.commit()
        return {"fit_score": 95, "verdict": "apply", "legit_confidence": 90, "red_flags": []}

    monkeypatch.setattr(scoring, "run_llm", slow_ai)
    with session_scope() as db:
        scoring.score_job(db, db.get(Job, job_id))
    with session_scope() as db:
        assert db.get(Job, job_id).status == JobStatus.REJECTED


def test_an_expired_job_that_returns_keeps_its_verdict():
    from jobagent.models import utcnow as now
    from jobagent.pipeline.ingest import expire_stale

    job_id, _ = _make("fp-revive", job_status=JobStatus.SHORTLISTED, app_status=None)
    with session_scope() as db:
        j = db.get(Job, job_id)
        j.source, j.last_seen_at = "remotive", now().replace(year=2020)
        db.commit()
        expire_stale(db, days=21)
        assert db.get(Job, job_id).status == JobStatus.EXPIRED and db.get(Job, job_id).expired_from == "shortlisted"


def test_a_blank_profile_matches_nothing(client):
    from jobagent.profiles import enabled_profiles

    r = client.post("/api/profiles", json={"name": "New profile", "enabled": True,
                                           "search": {"roles": [], "title_keywords": [], "locations": []}})
    pid = r.json()["id"]
    with session_scope() as db:
        assert pid not in dict(enabled_profiles(db))
    client.delete(f"/api/profiles/{pid}")


def test_a_bad_schedule_update_saves_nothing(client):
    before = client.get("/api/settings/schedule").json()["paused"]
    r = client.put("/api/settings/schedule", json={"paused": not before, "collect": {"time": "25:00"}})
    assert r.status_code == 400
    assert client.get("/api/settings/schedule").json()["paused"] == before


def test_writing_a_cover_letter_changes_only_the_letter(client, monkeypatch):
    from jobagent.pipeline import prepare

    monkeypatch.setattr(prepare, "run_llm", lambda *a, **k: {"cover_letter": "Dear team, ...", "short_pitch": "p"})
    _, app_id = _make("fp-cover-only", app_status=ApplicationStatus.APPROVED, answers={"Notice period?": "30 days"})
    r = client.post(f"/api/applications/{app_id}/cover")
    assert r.status_code == 200
    a = r.json()
    assert a["cover_letter"] == "Dear team, ..." and a["status"] == "approved" and a["answers"] == {"Notice period?": "30 days"}
    _, sent = _make("fp-cover-sent", job_status=JobStatus.APPLIED, app_status=ApplicationStatus.SUBMITTED,
                    submitted_at=utcnow())
    assert client.post(f"/api/applications/{sent}/cover").status_code == 409


def test_restart_recovery_leaves_work_a_live_process_is_doing():
    import subprocess

    from jobagent.bootstrap import recover_interrupted

    live = subprocess.Popen(["sleep", "30"])             # stands in for a CLI submit still running
    gone = subprocess.Popen(["true"])
    gone.wait()
    try:
        _, busy = _make("fp-live-worker", app_status=ApplicationStatus.SUBMITTING, worker_pid=live.pid)
        _, dead = _make("fp-dead-worker", app_status=ApplicationStatus.SUBMITTING, worker_pid=gone.pid)
        with session_scope() as db:
            recover_interrupted(db)
        assert _app(busy).status == ApplicationStatus.SUBMITTING
        assert _app(dead).status == ApplicationStatus.NEEDS_REVIEW
    finally:
        live.kill()
