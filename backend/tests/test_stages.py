"""Search profiles, per-profile matching, the stage schedule, source presets and the new API endpoints."""

from __future__ import annotations

import pytest

from jobagent.config import SearchProfile
from jobagent.models import Job, JobStatus, utcnow
from jobagent.pipeline.prefilter import match_profiles
from jobagent.profiles import from_resume_analysis, merge

PY = SearchProfile(roles=["Python Developer"], title_keywords=["python", "backend"], exclude_keywords=["intern", "manager"],
                   locations=["Bengaluru"], remote_ok=False, onsite_ok=True, min_prefilter_score=30, min_fit_score=70)
ML = SearchProfile(roles=["ML Engineer"], title_keywords=["machine learning", "ml engineer"], exclude_keywords=["intern"],
                   locations=["Remote"], remote_ok=True, onsite_ok=False, min_prefilter_score=30, min_fit_score=80,
                   max_age_days=30)


def _job(**kw) -> Job:
    base = dict(title="Backend Engineer (Python)", location="Bengaluru", remote=False, description="python fastapi " * 50,
                posted_at=utcnow(), source="greenhouse", company_name="Acme", url="https://x", fingerprint="f",
                status=JobStatus.NEW, duplicate_of=None)
    base.update(kw)
    return Job(**base)


def test_merge_unions_lists_and_keeps_only_shared_exclusions():
    m = merge([PY, ML])
    assert m.roles == ["Python Developer", "ML Engineer"]
    assert "machine learning" in m.title_keywords and "python" in m.title_keywords
    assert m.exclude_keywords == ["intern"]          # 'manager' is only excluded by one profile
    assert m.remote_ok and m.onsite_ok
    assert m.max_age_days == 30 and m.min_fit_score == 70


def test_match_profiles_records_every_matching_profile():
    score, reasons, ok, ids = match_profiles(_job(), [(1, PY), (2, ML)])
    assert ok and ids == [1]
    _, _, ok, ids = match_profiles(_job(title="ML Engineer", location="Remote", remote=True), [(1, PY), (2, ML)])
    assert ok and ids == [2]
    _, reasons, ok, ids = match_profiles(_job(title="Account Manager"), [(1, PY), (2, ML)])
    assert not ok and ids == []
    _, reasons, ok, _ = match_profiles(_job(duplicate_of=5), [(1, PY)])
    assert not ok and reasons[0].startswith("duplicate of")


def test_profile_from_resume_analysis():
    sp = from_resume_analysis({"suggested_roles": ["Backend Engineer"], "suggested_title_keywords": ["Python", "Django"],
                               "skills": ["Python", "Postgres"], "seniority": "junior"}, PY)
    assert sp.roles == ["Backend Engineer"] and sp.title_keywords == ["python", "django"]
    assert sp.seniority == ["junior"] and sp.locations == ["Bengaluru"]


def test_schedule_validation():
    from jobagent.scheduler import normalize_days, normalize_time

    assert normalize_days([3, 0, 3]) == [0, 3]
    assert normalize_time("8:05") == "08:05"
    with pytest.raises(ValueError):
        normalize_days([7])
    with pytest.raises(ValueError):
        normalize_time("25:00")


def test_schedule_api_and_plans(client):
    r = client.get("/api/settings/schedule")
    assert r.status_code == 200
    body = r.json()
    assert body["paused"] is True and body["stages"]["analyze"]["days"] == [0, 3]
    r = client.put("/api/settings/schedule", json={"analyze": {"days": [1, 4], "time": "10:30", "limit": 25}})
    assert r.status_code == 200 and r.json()["stages"]["analyze"]["days"] == [1, 4]
    assert r.json()["stages"]["analyze"]["limit"] == 25
    assert client.put("/api/settings/schedule", json={"collect": {"time": "99:00"}}).status_code == 400
    assert client.put("/api/settings/schedule", json={"apply_mode": "auto"}).status_code == 400   # env forbids
    assert client.put("/api/settings/runtime", json={"schedule.paused": False}).status_code == 400
    r = client.post("/api/settings/schedule/plan/light")
    assert r.status_code == 200 and r.json()["paused"] is False and r.json()["stages"]["analyze"]["days"] == [0, 3]
    r = client.post("/api/settings/schedule/plan/manual")
    assert r.json()["paused"] is True


def test_profiles_crud(client):
    r = client.get("/api/profiles")
    assert r.status_code == 200 and len(r.json()) == 1          # seeded from search.yaml
    first = r.json()[0]
    r = client.post("/api/profiles", json={"name": "Remote ML", "enabled": True, "search": ML.model_dump()})
    assert r.status_code == 200
    pid = r.json()["id"]
    r = client.put(f"/api/profiles/{pid}", json={"name": "Remote ML roles", "enabled": False, "search": ML.model_dump()})
    assert r.json()["name"] == "Remote ML roles" and r.json()["enabled"] is False
    assert client.delete(f"/api/profiles/{pid}").status_code == 200
    assert client.delete(f"/api/profiles/{first['id']}").status_code == 409     # keep at least one


def test_source_presets(client):
    r = client.get("/api/settings/source-presets")
    assert {p["id"] for p in r.json()} == {"india_remote", "remote", "india"}
    r = client.post("/api/settings/source-presets/remote")
    assert r.status_code == 200
    enabled = {s["name"]: s["enabled"] for s in client.get("/api/settings/sources").json()}
    assert enabled["himalayas"] is True and enabled["hasjob"] is False and enabled["greenhouse"] is True
    assert enabled["indeed"] is False                                   # terms-restricted sources are never switched on
    client.post("/api/settings/source-presets/india_remote")


def test_today_and_job_filters(client):
    r = client.get("/api/today")
    assert r.status_code == 200
    t = r.json()
    assert {"approvals", "strong_matches", "stages", "week", "setup"} <= t.keys()
    assert t["setup"]["profiles"] >= 1
    for params in ("unscored=true", "autofill=true", "not_applied=true&posted_within_days=7", "source_kind=ats,board",
                   "profile_id=1", "where=Bengaluru&min_fit=70"):
        assert client.get(f"/api/jobs?{params}").status_code == 200, params
    assert client.post("/api/jobs/bulk", json={"ids": [], "action": "reject"}).status_code == 400
    assert client.post("/api/jobs/bulk", json={"ids": [999999], "action": "reject"}).json() == {"updated": 0, "skipped": 0}


def test_job_filters_can_hide_jobs_that_dont_say(client):
    from jobagent.db import session_scope

    with session_scope() as db:
        for i, (mode, exp) in enumerate([("remote", 1.0), (None, None), ("onsite", 5.0)]):
            db.add(_job(fingerprint=f"fp-unstated-{i}", title=f"Unstated test {i}", work_mode=mode, exp_min=exp,
                        status=JobStatus.QUEUED, source="remotive"))
        db.commit()

    def titles(params: str) -> set[str]:
        return {j["title"] for j in client.get(f"/api/jobs?q=Unstated%20test&{params}").json()["items"]}

    assert titles("work_mode=remote") == {"Unstated test 0", "Unstated test 1"}
    assert titles("work_mode=remote&include_unstated=false") == {"Unstated test 0"}
    assert titles("max_experience=2&include_unstated=false") == {"Unstated test 0"}
    rows = client.get("/api/jobs/sources?status=queued").json()
    assert any(r["source"] == "remotive" and r["count"] >= 3 and r["label"] for r in rows)


def test_jobinfo_readers():
    from jobagent.utils.jobinfo import job_type, parse_experience, parse_salary, work_mode

    assert parse_experience("We need 3-5 years of experience with Python") == (3.0, 5.0)
    assert parse_experience("Experience required: 2 years") == (2.0, None)
    assert parse_experience("Founded 10 years ago. Experience with Django is a plus.") is None
    assert parse_experience("Freshers welcome") == (0.0, 1.0)
    assert parse_salary("₹ 6-12 LPA") == {"currency": "INR", "min": 600000.0, "max": 1200000.0}
    assert parse_salary("$120k - $150k")["max"] == 150000.0
    assert parse_salary("Depends on Experience") is None
    assert parse_salary("USD 5000-5000 monthly")["max"] == 60000.0          # the "m" of monthly is not million
    assert parse_salary("$60K – $70K, paid hourly")["max"] == 70000.0        # already annual
    assert parse_salary("USD 30-100 hourly")["max"] == 208000.0
    assert parse_salary("$1000 per task") is None and parse_salary("$230 – $350") is None
    assert work_mode("Dev", "Bengaluru (Hybrid)", False, "") == "hybrid"
    assert work_mode("Dev", "Pune", None, "") is None
    assert job_type("Python Intern", None, "") == "internship"
    assert job_type("Dev", None, "We offer internships for students") is None


def test_standard_filters_in_prefilter():
    from jobagent.utils.jobinfo import annotate

    sp = PY.model_copy(update={"experience_max": 3, "job_types": ["full_time"], "hybrid_ok": False,
                               "min_salary_inr": 800000, "exclude_companies": ["Acme Staffing"],
                               "must_not_mention": ["c2c"], "remote_ok": True})

    def run(**kw):
        j = _job(**kw)
        annotate(j)
        return match_profiles(j, [(1, sp)])

    assert run()[2] is True
    assert run(description="Need 5+ years of experience with python " * 20)[2] is False
    assert "years" in run(description="Need 5+ years of experience with python " * 20)[1][0]
    assert run(description="3-5 years of experience. python " * 20)[2] is True          # 3 <= limit
    assert run(location="Bengaluru (Hybrid)")[2] is False
    assert run(employment_type="Contract")[2] is False
    assert run(salary_text="₹ 4-6 LPA")[2] is False
    assert run(salary_text="₹ 10-14 LPA")[2] is True
    assert run(company_name="Acme Staffing Pvt Ltd")[2] is False
    assert run(description="python c2c only " * 30)[2] is False


def test_remote_jobs_tied_to_another_country_are_filtered():
    sp = PY.model_copy(update={"locations": ["Bengaluru", "India", "Remote"], "remote_ok": True})

    def ok(location: str, remote: bool = True) -> bool:
        return match_profiles(_job(location=location, remote=remote), [(1, sp)])[2]

    assert not ok("Remote - USA") and not ok("Dublin") and not ok("Remote (US only, US time zones)")
    assert ok("Remote: India") and ok("Bengaluru, Karnataka, India")      # the user's own places
    assert ok("Remote (Worldwide)") and ok("Anywhere") and ok("Remote") and ok("") and ok("Asia, APAC")
    assert ok("Remote UTC+5:30")


def test_outcome_tracking_flow(client):
    from jobagent.db import session_scope
    from jobagent.models import Application, Job, JobStatus

    with session_scope() as db:
        job = Job(fingerprint="fp-outcome", source="greenhouse", company_name="Acme", title="Backend Engineer",
                  url="https://x/1", status=JobStatus.APPLYING)
        db.add(job)
        db.flush()
        app = Application(job_id=job.id, status="needs_review", method="browser")
        db.add(app)
        db.flush()
        app_id = app.id
    assert client.patch(f"/api/applications/{app_id}", json={"outcome": "interview"}).status_code == 409   # not sent yet
    r = client.patch(f"/api/applications/{app_id}", json={"status": "submitted"})
    assert r.status_code == 200 and r.json()["outcome"] == "awaiting" and r.json()["follow_up_at"]
    r = client.patch(f"/api/applications/{app_id}", json={"outcome": "interview", "outcome_notes": "Round 1 on Monday"})
    assert r.json()["outcome"] == "interview" and r.json()["follow_up_at"]       # still open: reminder kept
    r = client.patch(f"/api/applications/{app_id}", json={"outcome": "rejected"})
    assert r.json()["follow_up_at"] is None                                      # closed: no reminder
    assert client.patch(f"/api/applications/{app_id}", json={"outcome": "ghost"}).status_code == 400
    with session_scope() as db:
        assert db.get(Application, app_id).job.status == JobStatus.APPLIED


def test_expire_stale_only_touches_unseen_board_jobs():
    from datetime import timedelta

    from jobagent.db import session_scope
    from jobagent.models import Job, JobStatus
    from jobagent.pipeline.ingest import expire_stale

    old = utcnow() - timedelta(days=40)
    with session_scope() as db:
        rows = [Job(fingerprint=f"fp-stale-{i}", source=src, company_name="Acme", title="Dev", url=f"https://x/s{i}",
                    status=JobStatus.QUEUED, last_seen_at=seen, discovered_at=old)
                for i, (src, seen) in enumerate([("remoteok", old), ("remoteok", utcnow()), ("greenhouse", old)])]
        db.add_all(rows)
        db.flush()
        ids = [r.id for r in rows]
    with session_scope() as db:
        assert expire_stale(db, days=21) >= 1
        assert [db.get(Job, i).status for i in ids] == [JobStatus.EXPIRED, JobStatus.QUEUED, JobStatus.QUEUED]


def test_source_health_states():
    from jobagent.db import session_scope
    from jobagent.health import source_health
    from jobagent.models import Run

    with session_scope() as db:
        db.add_all([
            Run(kind="crawl", source="h_fail", status="error", error="boom"),
            Run(kind="crawl", source="h_idle", status="ok", stats={}, log="Reed skipped: set JOBAGENT_REED_API_KEY"),
            Run(kind="crawl", source="h_block", status="partial", stats={"blocked": 1}),
            *[Run(kind="crawl", source="h_empty", status="ok", stats={"fetched": 0}, log="") for _ in range(3)],
            Run(kind="crawl", source="h_ok", status="ok", stats={"fetched": 12}),
        ])
    with session_scope() as db:
        h = source_health(db, ["h_fail", "h_idle", "h_block", "h_empty", "h_ok", "h_new"])
    assert {k: v["health"] for k, v in h.items()} == {"h_fail": "failing", "h_idle": "idle", "h_block": "blocked",
                                                     "h_empty": "empty", "h_ok": "ok", "h_new": "never"}
    assert "JOBAGENT_REED_API_KEY" in h["h_idle"]["note"]


def test_source_health_refused_and_nothing_to_crawl():
    from jobagent.db import session_scope
    from jobagent.health import source_health
    from jobagent.models import Company, Run

    with session_scope() as db:
        db.query(Company).filter(Company.ats_type == "workable").delete()
        db.add_all([Run(kind="crawl", source="h_403", status="ok", stats={"fetched": 0},
                        log="Foundit Python/India: HTTP 403 for https://x"),
                    *[Run(kind="crawl", source="workable", status="ok", stats={"fetched": 0}) for _ in range(3)]])
        db.commit()
        h = source_health(db, ["h_403", "workable"])
    assert h["h_403"]["health"] == "blocked" and "403" in h["h_403"]["note"]
    assert h["workable"]["health"] == "idle"            # no tracked company uses it: not a fault


def test_codex_rests_after_repeated_timeouts(monkeypatch):
    from jobagent.llm import client, codex_cli

    calls = []

    def hang(*a, **k):
        calls.append(1)
        raise client.LLMTimeout("Codex timed out after 240s")

    monkeypatch.setattr(codex_cli, "complete", hang)
    monkeypatch.setattr(client, "_timeouts", [])
    for _ in range(2):
        with pytest.raises(client.LLMTimeout):
            client.run_llm("hi", purpose="test", enforce_budget=True)
    with pytest.raises(client.LLMUnavailable, match="stopped answering"):
        client.run_llm("hi", purpose="test", enforce_budget=True)
    assert len(calls) == 2                                # the third call did not wait for Codex at all
    with pytest.raises(client.LLMTimeout):               # the AI settings test still tries for real
        client.run_llm("hi", purpose="test", enforce_budget=False)


def test_resume_refresh_endpoints(client):
    r = client.get("/api/profile/stale")
    assert r.status_code == 200 and {"since", "jobs", "drafts"} <= r.json().keys()
    t = client.get("/api/today").json()
    assert {"follow_ups", "outcomes", "sources_attention", "stale_resume"} <= t.keys()
