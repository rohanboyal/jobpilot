def test_health_and_settings(client):
    r = client.get("/api/pipeline/health")
    assert r.status_code == 200 and r.json()["ok"]
    s = client.get("/api/settings").json()
    assert "search" in s and "sources" in s and any(x["name"] == "greenhouse" for x in s["sources"])
    assert any(x["name"].startswith("site_") for x in s["sources"])


def test_jobs_and_stats_endpoints(client):
    assert client.get("/api/jobs").status_code == 200
    st = client.get("/api/stats").json()
    assert "funnel" in st and "budget" in st


def test_company_crud_and_detect(client):
    r = client.post("/api/companies", json={"name": "Test Co", "careers_url": "https://jobs.lever.co/testco"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ats_type"] == "lever" and body["ats_slug"] == "testco"
    assert client.post("/api/companies/detect", params={"url": "https://boards.greenhouse.io/foo"}).json()["ats_slug"] == "foo"
    r = client.patch(f"/api/companies/{body['id']}", json={"is_active": False})
    assert r.json()["is_active"] is False


def test_source_toggle_and_sites(client):
    r = client.put("/api/settings/sources", json={"remoteok": False})
    assert r.status_code == 200 and r.json()["remoteok"] is False
    sites = client.get("/api/settings/sites").json()
    assert any(s["key"] == "wellfound" for s in sites)


def test_profile_roundtrip(client):
    r = client.put("/api/profile", json={"headline": "Backend dev", "skills": ["python"]})
    assert r.json()["headline"] == "Backend dev"
    assert client.get("/api/profile").json()["skills"] == ["python"]


def test_company_patch_validation(client):
    r = client.post("/api/companies", json={"name": "Patch Co", "careers_url": "https://acme-patch.example/careers"})
    cid = r.json()["id"]
    assert client.patch(f"/api/companies/{cid}", json={"name": "  "}).status_code == 400
    assert client.patch(f"/api/companies/{cid}", json={"ats_type": "lever"}).status_code == 400
    assert client.patch(f"/api/companies/{cid}", json={"ats_type": "lever", "ats_slug": "patchco"}).status_code == 200


def test_submit_guards(client):
    from jobagent.db import session_scope
    from jobagent.models import Application, ApplicationStatus, Job, JobStatus, utcnow

    with session_scope() as db:
        job = Job(fingerprint="guard-1", source="lever", company_name="Guard Co", title="Engineer", url="https://jobs.lever.co/g/1",
                  status=JobStatus.APPLYING)
        db.add(job)
        db.flush()
        app = Application(job_id=job.id, status=ApplicationStatus.SUBMITTED, submitted_at=utcnow())
        db.add(app)
        db.commit()
        app_id = app.id
    assert client.post(f"/api/applications/{app_id}/approve").status_code == 409
    assert client.post(f"/api/applications/{app_id}/submit").status_code == 409
