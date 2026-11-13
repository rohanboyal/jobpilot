"""Several search profiles and resumes: a run covers the profiles the user ticks, together or one after another,
and every job is judged (and applied to) with the resume of the profile it matched."""

from __future__ import annotations

from collections.abc import Iterable

import pytest

from jobagent import tasks
from jobagent.config import SearchProfile
from jobagent.db import session_scope
from jobagent.models import Application, ApplicationStatus, Job, JobStatus, Profile, SearchProfileRow, utcnow
from jobagent.profiles import merge
from jobagent.sources.base import _REGISTRY, RawJob, Source, SourceContext

_DS = "Data scientist with six years of modelling, experimentation and causal inference in Python and SQL. " * 3
_AI = "Applied AI engineer who ships LLM retrieval, evaluation and agent systems to production at scale. " * 3


def _profile(name: str, roles: list[str], resume_id: int | None = None) -> int:
    with session_scope() as db:
        r = SearchProfileRow(name=name, enabled=True, resume_id=resume_id,
                             data=SearchProfile(roles=roles, title_keywords=[x.lower() for x in roles]).model_dump())
        db.add(r)
        db.commit()
        return r.id


def _resume(name: str, text: str) -> int:
    with session_scope() as db:
        p = Profile(name=name, resume_text=text, resume_path=f"/tmp/{name}.pdf", resume_filename=f"{name}.pdf")
        db.add(p)
        db.commit()
        return p.id


def _job(fp: str, title: str, profile_ids: list[int], status: str = JobStatus.QUEUED, score: int = 90) -> int:
    with session_scope() as db:
        j = Job(fingerprint=fp, source="greenhouse", company_name="Acme", title=title, url=f"https://x.test/{fp}",
                status=status, profile_ids=profile_ids, prefilter_score=score, fit_score=88 if status != "queued" else None)
        db.add(j)
        db.commit()
        return j.id


@pytest.fixture
def two_profiles(client):
    ds_resume, ai_resume = _resume("ds-resume", _DS), _resume("ai-resume", _AI)
    ds = _profile("Data Scientist", ["Data Scientist", "ML Scientist", "Analytics Lead"], ds_resume)
    ai = _profile("Applied AI", ["Applied AI Engineer", "LLM Engineer"], ai_resume)
    yield {"ds": ds, "ai": ai, "ds_resume": ds_resume, "ai_resume": ai_resume}
    with session_scope() as db:
        for pid in (ds, ai):
            db.delete(db.get(SearchProfileRow, pid))
        db.commit()


def test_merged_search_gives_every_profile_its_top_title():
    a = SearchProfile(roles=["Data Scientist", "ML Scientist", "Analytics Lead"])
    b = SearchProfile(roles=["Applied AI Engineer", "LLM Engineer"])
    c = SearchProfile(roles=["Backend Engineer"])
    merged = merge([a, b, c])
    assert merged.roles[:3] == ["Data Scientist", "Applied AI Engineer", "Backend Engineer"]
    ctx = SourceContext(settings=None, search=merged, db=None, log=print, profiles=3)
    assert Source.search_terms(ctx, 2) == merged.roles[:3]          # a site that reads 2 titles still covers all 3


def _stubs(monkeypatch, calls: list[tuple[str, list[str]]]) -> list[str]:
    def make(name: str, kind: str) -> type[Source]:
        class Stub(Source):
            def fetch(self, ctx: SourceContext) -> Iterable[RawJob]:
                calls.append((name, list(ctx.search.roles)))
                return []
        Stub.name, Stub.label, Stub.description, Stub.kind = name, name, name, kind
        return Stub

    for name, kind in (("stub_board", "ats"), ("stub_search", "board")):
        monkeypatch.setitem(_REGISTRY, name, make(name, kind))
    return ["stub_board", "stub_search"]


def test_a_run_searches_only_the_ticked_profiles(two_profiles, monkeypatch):
    calls: list[tuple[str, list[str]]] = []
    sources = _stubs(monkeypatch, calls)
    with session_scope() as db:
        tasks.collect_stage(db, print, sources=sources, profile_ids=[two_profiles["ai"]])
    assert {tuple(r) for _, r in calls} == {("Applied AI Engineer", "LLM Engineer")}


def test_one_after_another_is_a_pass_per_profile_and_reads_whole_boards_once(two_profiles, monkeypatch):
    calls: list[tuple[str, list[str]]] = []
    sources = _stubs(monkeypatch, calls)
    with session_scope() as db:
        tasks.collect_stage(db, print, sources=sources, profile_ids=[two_profiles["ds"], two_profiles["ai"]],
                            one_by_one=True)
    searched = [roles[0] for name, roles in calls if name == "stub_search"]
    assert searched == ["Data Scientist", "Applied AI Engineer"]
    assert [name for name, _ in calls].count("stub_board") == 1    # company boards don't depend on the search


def test_analyze_scores_only_the_ticked_profiles_with_their_own_resume(two_profiles, monkeypatch):
    from jobagent.pipeline import scoring

    prompts: list[str] = []
    monkeypatch.setattr(scoring, "run_llm", lambda prompt, **k: prompts.append(prompt) or
                        {"fit_score": 80, "verdict": "apply", "legit_confidence": 90, "red_flags": []})
    ai_job = _job("fp-ai-1", "LLM Engineer", [two_profiles["ai"]], score=99)
    ds_job = _job("fp-ds-1", "Data Scientist", [two_profiles["ds"]], score=99)
    with session_scope() as db:
        scoring.score_queued(db, limit=50, profile_ids=[two_profiles["ai"]])
        assert db.get(Job, ai_job).fit_score == 80 and db.get(Job, ds_job).status == JobStatus.QUEUED
    assert prompts and all(_AI[:40] in p and _DS[:40] not in p for p in prompts)
    prompts.clear()
    with session_scope() as db:
        scoring.score_job(db, db.get(Job, ds_job))                  # judged by its own profile: the data science resume
    assert _DS[:40] in prompts[0]


def test_a_job_on_two_profiles_uses_the_resume_of_the_ticked_one(two_profiles, monkeypatch):
    from jobagent.pipeline import prepare

    prompts: list[str] = []
    monkeypatch.setattr(prepare, "run_llm", lambda prompt, **k: prompts.append(prompt) or
                        {"cover_letter": "Dear team", "short_pitch": "pitch"})
    both = _job("fp-both", "ML Engineer", [two_profiles["ds"], two_profiles["ai"]], status=JobStatus.SHORTLISTED)
    with session_scope() as db:
        app = prepare.prepare_application(db, both, cover="always", among=[two_profiles["ai"]])
        assert app.resume_id == two_profiles["ai_resume"] and app.resume_path.endswith("ai-resume.pdf")
    assert _AI[:40] in prompts[0]


def test_resumes_can_be_added_named_assigned_and_deleted(client, two_profiles):
    text = "Senior backend engineer: Python, Go, distributed systems, Postgres, Kafka and on-call leadership. " * 3
    first = client.post("/api/resumes", files={"file": ("main.txt", text.encode(), "text/plain")})
    assert first.status_code == 200                              # fills the default slot if it was still empty
    r = client.post("/api/resumes", files={"file": ("backend.txt", text.encode(), "text/plain")},
                    data={"name": "Backend resume"})
    rid = r.json()["id"]
    assert rid != 1 and r.json()["name"] == "Backend resume"
    listed = {x["id"]: x for x in client.get("/api/resumes").json()}
    assert rid in listed and listed[two_profiles["ai_resume"]]["used_by"][0]["name"] == "Applied AI"
    assert client.put(f"/api/resumes/{rid}", json={"name": "Backend (2026)"}).json()["name"] == "Backend (2026)"
    # a profile picks it; deleting the resume sends the profile back to the default one
    row = client.get("/api/profiles").json()
    ds = next(p for p in row if p["id"] == two_profiles["ds"])
    assert client.put(f"/api/profiles/{ds['id']}", json={**ds, "resume_id": rid}).json()["resume_id"] == rid
    assert client.put(f"/api/profiles/{ds['id']}", json={**ds, "resume_id": 9999}).status_code == 400
    assert client.delete(f"/api/resumes/{rid}").json()["removed"] == rid
    assert next(p for p in client.get("/api/profiles").json() if p["id"] == ds["id"])["resume_id"] is None


def test_an_application_can_switch_resume_until_it_is_sent(client, two_profiles):
    with session_scope() as db:
        job = _job("fp-switch", "LLM Engineer", [two_profiles["ai"]], status=JobStatus.APPLYING)
        open_app = Application(job_id=job, status=ApplicationStatus.NEEDS_REVIEW, method="browser")
        sent = Application(job_id=job, status=ApplicationStatus.SUBMITTED, method="browser", submitted_at=utcnow())
        db.add_all([open_app, sent])
        db.commit()
        open_id, sent_id = open_app.id, sent.id
    r = client.patch(f"/api/applications/{open_id}", json={"resume_id": two_profiles["ds_resume"]})
    assert r.status_code == 200 and r.json()["resume_path"].endswith("ds-resume.pdf")
    assert client.patch(f"/api/applications/{sent_id}", json={"resume_id": two_profiles["ds_resume"]}).status_code == 409


def test_run_requests_only_accept_profiles_that_can_run(client, two_profiles, monkeypatch):
    started: list[dict] = []
    monkeypatch.setattr(tasks, "start", lambda kind, label, fn, *a, **kw: started.append({"label": label, **kw}) or {"id": "t"})
    assert client.post("/api/pipeline/cycle", json={"profile_ids": []}).status_code == 400
    assert client.post("/api/pipeline/cycle", json={"profile_ids": [987654]}).status_code == 400
    ids = [two_profiles["ds"], two_profiles["ai"]]
    assert client.post("/api/pipeline/cycle", json={"profile_ids": ids, "one_by_one": True}).status_code == 200
    assert started[-1]["profile_ids"] == ids and started[-1]["one_by_one"] is True
    assert "Data Scientist, Applied AI one after another" in started[-1]["label"]
    est = client.get(f"/api/pipeline/estimate?stage=analyze&profile_ids={ids[0]},{ids[1]}&one_by_one=true").json()
    assert set(est) == {"collect_ai", "analyze_ai", "total_ai", "left"} and est["collect_ai"] == 0


def test_a_signed_in_site_is_searched_once_a_day_per_profile():
    from datetime import timedelta

    from jobagent import pacing
    from jobagent.models import Run

    with session_scope() as db:
        t = utcnow() - timedelta(hours=2)
        db.add(Run(kind="crawl", source="site_profiles", status="ok", started_at=t, finished_at=t,
                   stats={"fetched": 4, "profiles": [1, 2]}, log=""))
        db.commit()
        assert pacing.skip_reason(db, "site_profiles", [2]) is not None     # already searched for it today
        assert pacing.skip_reason(db, "site_profiles", [3]) is None         # a profile it hasn't searched for yet


def test_years_of_experience_come_from_the_role_dates():
    from datetime import date

    from jobagent.pipeline.profile import years_from_experience

    today = date(2026, 11, 8)
    roles = [{"title": "Artificial Intelligence Engineer", "start": "Oct 2026", "end": "Present"},
             {"title": "Full Stack Engineer", "start": "Oct 2025", "end": "Oct 2026"},
             {"title": "Backend Intern / Software Trainee", "start": "Apr 2025", "end": "Sep 2025"}]
    assert years_from_experience(roles, today) == 1.1                   # Oct 2025 to today, overlap counted once
    assert years_from_experience(roles[2:], today) == 0.5               # only internships: they count
    assert years_from_experience([{"title": "Dev", "start": "2019", "end": "2021"}], today) == 3.0
    assert years_from_experience([{"title": "Dev", "start": "03/2022", "end": "September 2023"}], today) == 1.6
    assert years_from_experience([{"title": "Dev", "start": "", "end": "Present"}], today) is None


def test_analysis_replaces_a_zero_estimate_with_the_dated_total(client, monkeypatch):
    from jobagent.pipeline import profile

    rid = _resume("dated", _AI)
    monkeypatch.setattr(profile, "run_llm", lambda *a, **k: {
        "headline": "AI engineer", "summary": "s", "skills": ["python"], "years_experience": 0, "seniority": "junior",
        "suggested_roles": ["AI Engineer"], "suggested_title_keywords": ["ai"], "education": [], "projects": [],
        "contact": {}, "experience": [{"title": "AI Engineer", "company": "X", "start": "Jan 2020", "end": "Dec 2021",
                                       "highlights": []}]})
    with session_scope() as db:
        assert profile.analyze_profile(db, rid)["years_experience"] == 2.0
        assert db.get(Profile, rid).years_experience == 2.0
