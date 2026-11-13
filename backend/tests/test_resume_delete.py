"""Deleting resumes (the default one too) and what that does to profiles, applications, files and Refresh."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from jobagent.api.profile import _stale
from jobagent.config import SearchProfile, get_settings
from jobagent.db import session_scope
from jobagent.models import Application, ApplicationStatus, Job, JobStatus, Profile, SearchProfileRow, utcnow

_TEXT = "Applied AI engineer: LLM retrieval, evaluation, agents, FastAPI services and React front ends in production. " * 3
_LONG_AGO = (utcnow() - timedelta(days=2)).isoformat()


@pytest.fixture
def mine(client):
    """These tests must know every resume: set the others aside, and put everything back afterwards."""
    cols = [c.key for c in Profile.__table__.columns]
    with session_scope() as db:
        saved = [{c: getattr(p, c) for c in cols} for p in db.scalars(select(Profile)).all()]
        picks = {r.id: (r.resume_id, r.resume_changed_at) for r in db.scalars(select(SearchProfileRow)).all()}
        for p in db.scalars(select(Profile)).all():
            db.delete(p)
    made: dict[str, list[int]] = {"jobs": [], "profiles": []}
    yield made
    with session_scope() as db:
        for jid in made["jobs"]:
            db.delete(db.get(Job, jid))
        for pid in made["profiles"]:
            db.delete(db.get(SearchProfileRow, pid))
        for p in db.scalars(select(Profile)).all():
            db.delete(p)
        db.flush()
        db.add_all(Profile(**d) for d in saved)
        for r in db.scalars(select(SearchProfileRow)).all():
            if r.id in picks:
                r.resume_id, r.resume_changed_at = picks[r.id]


def _resume(rid: int | None, name: str) -> tuple[int, str]:
    path = get_settings().resume_dir / f"{name}.pdf"
    path.write_bytes(b"%PDF " + name.encode())
    with session_scope() as db:
        p = Profile(id=rid, name=name, resume_text=_TEXT, resume_path=str(path), resume_filename=path.name,
                    extra={"resume_uploaded_at": _LONG_AGO})
        db.add(p)
        db.flush()
        return p.id, str(path)


def _profile(made: dict, name: str, resume_id: int | None) -> int:
    with session_scope() as db:
        r = SearchProfileRow(name=name, enabled=True, resume_id=resume_id,
                             data=SearchProfile(roles=[name], title_keywords=[name.lower()]).model_dump())
        db.add(r)
        db.flush()
        made["profiles"].append(r.id)
        return r.id


def _job(made: dict, fp: str, pid: int) -> int:
    with session_scope() as db:
        title = db.get(SearchProfileRow, pid).name           # matches its profile, so a re-check keeps the tag
        j = Job(fingerprint=fp, source="greenhouse", company_name="Acme", title=title, url=f"https://x.test/{fp}",
                status=JobStatus.SHORTLISTED, profile_ids=[pid], fit_score=85, scored_at=utcnow() - timedelta(hours=1))
        db.add(j)
        db.flush()
        made["jobs"].append(j.id)
        return j.id


def _app(job_id: int, resume_id: int | None, path: str, sent: bool = False) -> int:
    with session_scope() as db:
        a = Application(job_id=job_id, method="browser", resume_id=resume_id, resume_path=path, cover_letter="Dear team",
                        status=ApplicationStatus.SUBMITTED if sent else ApplicationStatus.NEEDS_REVIEW,
                        submitted_at=utcnow() if sent else None, drafted_at=utcnow() - timedelta(hours=1))
        db.add(a)
        db.flush()
        return a.id


def test_deleting_the_default_resume_moves_the_next_one_into_its_place(client, mine):
    _, old_path = _resume(1, "old-default")
    heir, heir_path = _resume(None, "new-default")
    on_default, on_heir = _profile(mine, "Backend", None), _profile(mine, "Applied AI", heir)
    j_default, j_heir = _job(mine, "fp-del-default", on_default), _job(mine, "fp-del-heir", on_heir)
    open_default, sent_default = _app(j_default, 1, old_path), _app(j_default, 1, old_path, sent=True)
    open_heir = _app(j_heir, heir, heir_path)
    with session_scope() as db:
        before = _stale(db)
    assert j_default not in before["job_ids"] and j_heir not in before["job_ids"]

    r = client.delete("/api/resumes/1").json()
    assert r == {"ok": True, "removed": heir, "default": "new-default"}
    listed = client.get("/api/resumes").json()
    assert [(x["id"], x["name"], x["is_default"]) for x in listed] == [(1, "new-default", True)]
    with session_scope() as db:
        assert db.get(Profile, 1).resume_path == heir_path and db.get(Profile, heir) is None
        rows = {pid: db.get(SearchProfileRow, pid) for pid in (on_default, on_heir)}
        assert rows[on_heir].resume_id is None and rows[on_heir].resume_changed_at is None     # same resume as before
        assert rows[on_default].resume_changed_at is not None                                  # judged with the old one
        apps = {aid: db.get(Application, aid) for aid in (open_default, sent_default, open_heir)}
        assert (apps[open_default].resume_id, apps[open_default].resume_path) == (None, heir_path)
        assert (apps[open_heir].resume_id, apps[open_heir].resume_path) == (None, heir_path)
        assert apps[sent_default].resume_path == old_path            # what was sent stays on record...
        stale = _stale(db)
    assert Path(old_path).exists()                                    # ...and so does its file
    assert j_default in stale["job_ids"] and j_heir not in stale["job_ids"]
    assert open_default in stale["app_ids"] and open_heir not in stale["app_ids"]

    # Deleting the only resume leaves none: unsent applications lose the file, which goes when nothing uses it.
    r = client.delete("/api/resumes/1").json()
    assert r == {"ok": True, "removed": None, "default": None}            # the default row stays, empty
    listed = client.get("/api/resumes").json()
    assert len(listed) == 1 and not listed[0]["has_text"] and listed[0]["resume_filename"] is None
    assert client.get("/api/today").json()["setup"]["has_resume"] is False
    with session_scope() as db:
        assert db.get(Application, open_heir).resume_path is None
        assert db.get(Application, sent_default).resume_path == old_path
    assert not Path(heir_path).exists() and Path(old_path).exists()


def test_deleting_another_resume_marks_the_profiles_that_fall_back(client, mine):
    _resume(1, "main")
    other, other_path = _resume(None, "data-science")
    pid = _profile(mine, "Data Scientist", other)
    jid = _job(mine, "fp-del-other", pid)
    assert client.delete(f"/api/resumes/{other}").json()["removed"] == other
    assert not Path(other_path).exists()
    with session_scope() as db:
        assert db.get(SearchProfileRow, pid).resume_id is None
        assert jid in _stale(db)["job_ids"]                              # scored with the deleted resume


def test_switching_a_profile_to_another_resume_marks_its_scores_for_refresh(client, mine):
    _resume(1, "main")
    other, _ = _resume(None, "applied-ai")
    pid = _profile(mine, "Applied AI", None)
    jid = _job(mine, "fp-switch-resume", pid)
    with session_scope() as db:
        assert jid not in _stale(db)["job_ids"]
    row = next(p for p in client.get("/api/profiles").json() if p["id"] == pid)
    assert client.put(f"/api/profiles/{pid}", json={**row, "resume_id": other}).status_code == 200
    with session_scope() as db:
        assert jid in _stale(db)["job_ids"]


def test_a_new_file_never_overwrites_one_a_sent_application_used(client, mine):
    first = client.post("/api/resumes", files={"file": ("cv.txt", _TEXT.encode(), "text/plain")}).json()
    sent_path = first["resume_path"]
    pid = _profile(mine, "Backend", None)
    _app(_job(mine, "fp-overwrite", pid), 1, sent_path, sent=True)
    again = client.post("/api/resumes/1/file", files={"file": ("cv.txt", (_TEXT + " Updated.").encode(), "text/plain")})
    assert again.status_code == 200 and again.json()["resume_path"] != sent_path
    assert Path(sent_path).read_text() == _TEXT and Path(again.json()["resume_path"]).name == "cv-2.txt"
