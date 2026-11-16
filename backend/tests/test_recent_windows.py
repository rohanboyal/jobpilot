"""Today shows jobs found in the last 7 days; the Jobs lists keep 30 days (jobs with an application always stay)."""

from __future__ import annotations

from datetime import timedelta

from jobagent.db import session_scope
from jobagent.models import Application, ApplicationStatus, Job, JobStatus, utcnow


def _job(fp: str, days_ago: int, status: str = JobStatus.SHORTLISTED, fit: int = 90) -> int:
    with session_scope() as db:
        j = Job(fingerprint=fp, source="greenhouse", company_name="Windows Co", title=f"AI Engineer {fp}",
                url=f"https://x.test/{fp}", status=status, fit_score=fit, scored_at=utcnow(),
                discovered_at=utcnow() - timedelta(days=days_ago))
        db.add(j)
        db.flush()
        return j.id


def _app(job_id: int) -> int:
    with session_scope() as db:
        a = Application(job_id=job_id, status=ApplicationStatus.NEEDS_REVIEW, method="browser", cover_letter="Hi")
        db.add(a)
        db.flush()
        return a.id


def test_today_shows_the_last_week_and_counts_older_approvals(client):
    fresh, week_old, month_old = _job("win-fresh", 2), _job("win-9d", 9), _job("win-40d", 40)
    fresh_app, old_app = _app(fresh), _app(week_old)
    t = client.get("/api/today").json()
    assert t["recent_days"] == 7
    shown = {a["id"] for a in t["approvals"]}
    assert fresh_app in shown and old_app not in shown and t["older_approvals"] >= 1
    strong = {j["id"] for j in t["strong_matches"]}
    assert week_old not in strong and month_old not in strong
    assert all(a["job"]["discovered_at"] for a in t["approvals"])            # the card's "found 2 days ago"


def test_jobs_lists_keep_thirty_days_but_never_drop_applied_jobs(client):
    recent, old, old_applied = _job("keep-20d", 20), _job("keep-45d", 45), _job("keep-45d-app", 45)
    _app(old_applied)
    ids = {j["id"] for j in client.get("/api/jobs?q=Windows Co&page_size=200").json()["items"]}
    assert recent in ids and old not in ids and old_applied in ids


def test_analyze_skips_jobs_older_than_the_lists_keep(client, monkeypatch):
    from jobagent.pipeline import scoring

    old = _job("score-60d", 60, status=JobStatus.QUEUED, fit=None)
    picked: list[int] = []
    monkeypatch.setattr(scoring, "_score_rows", lambda db, rows, log, **kw: picked.extend(j.id for j in rows) or {})
    with session_scope() as db:
        scoring.score_queued(db, limit=500)
    assert old not in picked
