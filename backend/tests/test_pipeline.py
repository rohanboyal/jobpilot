from datetime import UTC, datetime, timedelta

from jobagent.config import SearchProfile
from jobagent.db import session_scope
from jobagent.models import Job, JobStatus
from jobagent.pipeline.ingest import ingest_raw
from jobagent.pipeline.prefilter import prefilter_job
from jobagent.pipeline.scoring import heuristic_trust
from jobagent.sources.base import RawJob

SEARCH = SearchProfile(roles=["Python Developer"], title_keywords=["python", "backend"], exclude_keywords=["intern"],
                       skills=["python", "fastapi", "postgres"], locations=["India", "Remote"], remote_ok=True,
                       max_age_days=14, min_prefilter_score=30)


def _job(**kw) -> Job:
    base = dict(fingerprint="x", source="greenhouse", company_name="Acme", title="Backend Python Engineer",
                location="Bengaluru, India", url="https://a", description="python fastapi postgres " * 50,
                posted_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=2), status=JobStatus.NEW)
    base.update(kw)
    return Job(**base)


def test_prefilter_passes_good_job():
    score, reasons, ok = prefilter_job(_job(), SEARCH)
    assert ok and score >= 70 and any("skills" in r for r in reasons)


def test_prefilter_rejects_excluded_title_and_location():
    assert prefilter_job(_job(title="Python Intern"), SEARCH)[2] is False
    assert prefilter_job(_job(location="Berlin, Germany", remote=False), SEARCH)[2] is False
    assert prefilter_job(_job(location="Berlin, Germany", remote=True), SEARCH)[2] is False   # remote, Germany only
    assert prefilter_job(_job(location="Remote (Worldwide)", remote=True), SEARCH)[2] is True
    assert prefilter_job(_job(title="Account Manager"), SEARCH)[2] is False
    assert prefilter_job(_job(posted_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=40)), SEARCH)[2] is False


def test_heuristic_trust_flags_scams():
    good = _job()
    bad = _job(source="linkedin", description="Earn Rs 50,000 weekly! Pay a small registration fee. Contact on WhatsApp gmail.com",
               company_name="Leading MNC")
    assert heuristic_trust(good)[0] > 70
    score, flags = heuristic_trust(bad)
    assert score < 40 and "asks for a fee" in flags


def test_ingest_dedups_across_sources(client):
    from jobagent.sources.base import all_sources

    prios = {n: c.priority for n, c in all_sources().items()}
    with session_scope() as db:
        stats, cache = {}, {}
        li = ingest_raw(db, RawJob(source="linkedin", external_id="li1", title="Backend Python Engineer", company_name="Acme Corp",
                                   url="https://linkedin.com/jobs/view/1", location="Bengaluru, India"), 3, prios, stats, cache)
        db.commit()
        gh = ingest_raw(db, RawJob(source="greenhouse", external_id="gh1", title="Backend Python Engineer", company_name="Acme Corp",
                                   url="https://boards.greenhouse.io/acme/jobs/1", location="Bengaluru"), 1, prios, stats, cache)
        db.commit()
        assert stats["new"] == 2 and stats["duplicates"] == 1
        db.refresh(li)
        assert li.duplicate_of == gh.id and li.status == JobStatus.FILTERED_OUT
        assert gh.duplicate_of is None and gh.status == JobStatus.NEW
        # re-ingesting the same raw job updates instead of duplicating
        again = ingest_raw(db, RawJob(source="greenhouse", external_id="gh1", title="Backend Python Engineer", company_name="Acme Corp",
                                      url="https://boards.greenhouse.io/acme/jobs/1", description="long " * 100), 1, prios, stats, cache)
        assert again.id == gh.id and stats["updated"] == 1 and again.description


def _prios():
    from jobagent.sources.base import all_sources

    return {n: c.priority for n, c in all_sources().items()}


def test_same_board_postings_are_not_duplicates(client):
    prios = _prios()
    with session_scope() as db:
        stats, cache = {}, {}
        a = ingest_raw(db, RawJob(source="greenhouse", external_id="a1", title="Staff Software Engineer", company_name="Databricks",
                                  url="https://boards.greenhouse.io/databricks/jobs/1", location="Bengaluru"), 1, prios, stats, cache)
        db.commit()
        b = ingest_raw(db, RawJob(source="greenhouse", external_id="a2", title="Staff Software Engineer (Data Platform)",
                                  company_name="Databricks", url="https://boards.greenhouse.io/databricks/jobs/2", location="Bengaluru"),
                       1, prios, stats, cache)
        db.commit()
        c = ingest_raw(db, RawJob(source="greenhouse", external_id="a3", title="Staff Software Engineer", company_name="Databricks",
                                  url="https://boards.greenhouse.io/databricks/jobs/3", location="Bengaluru"), 1, prios, stats, cache)
        db.commit()
        for j in (a, b, c):
            db.refresh(j)
            assert j.status == JobStatus.NEW and j.duplicate_of is None
        assert stats.get("duplicates", 0) == 0


def test_expired_twin_never_wins_and_applied_row_always_wins(client):
    prios = _prios()
    with session_scope() as db:
        stats, cache = {}, {}
        gh = ingest_raw(db, RawJob(source="greenhouse", external_id="e1", title="Platform Engineer", company_name="Zeta Co",
                                   url="https://boards.greenhouse.io/zeta/jobs/1", location="Pune"), 1, prios, stats, cache)
        db.commit()
        gh.status = JobStatus.EXPIRED
        db.commit()
        li = ingest_raw(db, RawJob(source="linkedin", external_id="e2", title="Platform Engineer", company_name="Zeta Co",
                                   url="https://www.linkedin.com/jobs/view/2", location="Pune, India"), 3, prios, stats, cache)
        db.commit()
        db.refresh(li)
        db.refresh(gh)
        assert li.status == JobStatus.NEW and li.duplicate_of is None      # the live row stays visible
        assert gh.duplicate_of == li.id                                    # the expired one is hidden behind it

        # user applied through the LinkedIn row; a better source arriving later must not re-run the pipeline
        li.status = JobStatus.APPLIED
        db.commit()
        gh2 = ingest_raw(db, RawJob(source="lever", external_id="e3", title="Platform Engineer", company_name="Zeta Co",
                                    url="https://jobs.lever.co/zeta/3", location="Pune"), 1, prios, stats, cache)
        db.commit()
        db.refresh(gh2)
        db.refresh(li)
        assert gh2.duplicate_of == li.id and gh2.status == JobStatus.FILTERED_OUT
        assert li.status == JobStatus.APPLIED and li.duplicate_of is None


def test_expiry_promotes_live_twin(client):
    from datetime import timedelta

    from jobagent.models import Company
    from jobagent.pipeline.ingest import _expire_missing

    prios = _prios()
    with session_scope() as db:
        co = Company(name="Omega Ltd", ats_type="ashby", ats_slug="omega", origin="user")
        db.add(co)
        db.commit()
        stats, cache = {}, {}
        ash = ingest_raw(db, RawJob(source="ashby", external_id="o1", title="Data Engineer", company_name="Omega Ltd",
                                    url="https://jobs.ashbyhq.com/omega/1", location="Remote", company_id=co.id, ats_type="ashby", ats_slug="omega"),
                         1, prios, stats, cache)
        db.commit()
        li = ingest_raw(db, RawJob(source="linkedin", external_id="o2", title="Data Engineer", company_name="Omega Ltd",
                                   url="https://www.linkedin.com/jobs/view/9", location="Remote"), 3, prios, stats, cache)
        db.commit()
        db.refresh(li)
        assert li.duplicate_of == ash.id and li.status == JobStatus.FILTERED_OUT
        # next crawl of the board no longer lists the Ashby posting
        started = datetime.now(UTC).replace(tzinfo=None) + timedelta(seconds=1)
        co.last_crawled_at = started + timedelta(seconds=1)
        db.commit()
        _expire_missing(db, "ashby", [co], started, stats, truncated=set())
        db.refresh(ash)
        db.refresh(li)
        assert ash.status == JobStatus.EXPIRED and ash.duplicate_of == li.id
        assert li.duplicate_of is None and li.status == JobStatus.NEW
        # a truncated board never expires anything
        ash.status = JobStatus.NEW
        ash.last_seen_at = started - timedelta(days=1)
        db.commit()
        _expire_missing(db, "ashby", [co], started, {}, truncated={co.id})
        db.refresh(ash)
        assert ash.status == JobStatus.NEW
