"""A profile built from a resume searches that resume's kind of job: an AI engineer's profile lets AI/LLM titles
through and keeps plain backend, full-stack and unrelated titles out."""

from __future__ import annotations

from jobagent.config import SearchProfile
from jobagent.llm.prompts import SCORE_SYSTEM
from jobagent.models import Job
from jobagent.pipeline.prefilter import prefilter_job
from jobagent.profiles import clean_title_keywords, from_resume_analysis
from jobagent.utils.text import title_has


def test_short_keywords_match_whole_words_only():
    assert title_has("ai engineer", "ai") and title_has("generative ai developer", "ai")
    assert title_has("ai/ml engineer", "ai") and title_has("senior ai-platform engineer", "ai")
    assert not title_has("maintenance technician", "ai") and not title_has("chairman of the board", "ai")
    assert not title_has("email marketing lead", "ai")
    assert title_has("llm engineer", "llm") and title_has("machine learning engineer", "machine learning")
    assert title_has("engineering manager", "engineer")          # longer keywords still match word starts


def test_generic_words_never_become_title_keywords():
    words = ["artificial", "intelligence", "engineer", "ai", "applied", "llm", "full", "stack", "Software",
             "machine learning", "AI Engineer", "ai engineer", "developer"]
    assert clean_title_keywords(words) == ["ai", "llm", "machine learning", "ai engineer"]


def _passes(search: SearchProfile, title: str) -> bool:
    job = Job(fingerprint="t", source="greenhouse", company_name="Acme", title=title, url="https://x.test",
              location="Remote", remote=True, description="")
    return prefilter_job(job, search)[2]


def test_an_ai_resume_profile_keeps_backend_and_unrelated_titles_out():
    analysis = {"suggested_roles": ["AI Engineer", "Applied AI Engineer", "LLM Engineer"],
                "suggested_title_keywords": ["ai", "llm", "engineer", "machine learning", "full", "stack", "software"],
                "skills": ["python", "langchain"], "years_experience": 1.1, "seniority": "junior"}
    search = from_resume_analysis(analysis, SearchProfile(locations=["Remote"]))
    assert search.title_keywords == ["ai", "llm", "machine learning"]
    # acronyms in the titles always count, even when the suggested keywords leave them out
    narrow = from_resume_analysis({**analysis, "suggested_title_keywords": ["applied ai", "ai automation"]}, SearchProfile())
    assert narrow.title_keywords == ["ai", "llm", "applied ai", "ai automation"]
    for ok in ("AI Engineer", "Generative AI Engineer", "LLM Engineer", "Machine Learning Engineer", "AI/ML Developer"):
        assert _passes(search, ok), ok
    for no in ("Backend Engineer", "Full Stack Developer", "Software Engineer", "Maintenance Engineer",
               "Python Developer"):
        assert not _passes(search, no), no


def test_scoring_treats_other_kinds_of_work_as_poor_fits():
    assert "target_roles" in SCORE_SYSTEM and "below 50" in SCORE_SYSTEM


def test_a_resume_makes_one_profile_with_a_short_name_not_duplicates(client):
    from jobagent.db import session_scope
    from jobagent.models import Profile, SearchProfileRow

    with session_scope() as db:
        p = Profile(name="Data resume", resume_text="Data scientist with experiments and causal inference. " * 5,
                    extra={"suggested_roles": ["Data Scientist", "ML Scientist"], "suggested_title_keywords": ["data scientist"]})
        db.add(p)
        db.flush()
        rid = p.id
    first = client.post(f"/api/profiles/from-resume?resume_id={rid}")
    assert first.status_code == 200 and first.json()["name"] == "Data Scientist"
    again = client.post(f"/api/profiles/from-resume?resume_id={rid}")
    assert again.status_code == 409 and '"Data Scientist" already searches' in again.json()["detail"]
    with session_scope() as db:
        db.delete(db.get(SearchProfileRow, first.json()["id"]))
        db.delete(db.get(Profile, rid))
