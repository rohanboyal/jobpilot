"""Prompt builders and JSON schemas for every AI task."""

from __future__ import annotations

import json
import re
from typing import Any

from ..config import SearchProfile
from ..utils.text import truncate

SCORE_SYSTEM = (
    "You are a meticulous technical recruiter helping ONE specific candidate decide which jobs to apply to. "
    "You read a candidate profile and a job posting and return a strict JSON assessment. "
    "Be calibrated: 90+ means an obvious match they should apply to today; 70-89 a solid match; 50-69 a stretch; "
    "below 50 do not apply. The candidate's target_roles say which kind of job they want: a job outside that kind of "
    "work scores below 50 even when many skills overlap (a plain backend or web job is not an AI/ML engineering job, a "
    "data analyst job is not a data scientist job). Judge seniority, core stack, location/remote constraints and visa "
    "realities honestly. "
    "Also check whether the posting looks like a genuine employer posting rather than a scam or lead-generation ad."
)

SCORE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "fit_score": {"type": "integer", "minimum": 0, "maximum": 100},
        "verdict": {"type": "string", "enum": ["apply", "maybe", "skip"]},
        "one_liner": {"type": "string", "description": "<= 20 words: why this score"},
        "strengths": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
        "gaps": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
        "seniority_match": {"type": "string", "enum": ["under", "match", "over", "unclear"]},
        "location_match": {"type": "string", "enum": ["yes", "remote_ok", "no", "unclear"]},
        "salary_note": {"type": "string"},
        "pitch": {"type": "string", "description": "2-3 sentences the candidate could use to open a cover letter"},
        "legit_confidence": {"type": "integer", "minimum": 0, "maximum": 100,
                              "description": "How confident you are this is a genuine job from a real employer"},
        "red_flags": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
        "tags": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
    },
    "required": ["fit_score", "verdict", "one_liner", "strengths", "gaps", "seniority_match",
                 "location_match", "pitch", "legit_confidence", "red_flags"],
    "additionalProperties": False,
}


def build_score_prompt(profile_text: str, search: SearchProfile, job: dict[str, Any]) -> str:
    prefs = {
        "target_roles": search.roles,
        "seniority": search.seniority,
        "locations": search.locations,
        "remote_ok": search.remote_ok,
        "onsite_ok": search.onsite_ok,
        "key_skills": search.skills,
        "experience_years_wanted": [search.experience_min, search.experience_max],
        "hybrid_ok": search.hybrid_ok,
        "job_types": search.job_types or "any",
        "min_salary_inr_per_year": search.min_salary_inr,
        "min_salary_usd_per_year": search.min_salary_usd,
    }
    return (
        "## Candidate profile\n"
        f"{truncate(profile_text, 9000) or '(no resume uploaded yet: judge only against the preferences below)'}\n\n"
        "## Candidate preferences\n"
        f"{json.dumps(prefs, ensure_ascii=False)}\n\n"
        "## Job posting\n"
        f"Source: {job.get('source')}\n"
        f"Company: {job.get('company_name')}\n"
        f"Title: {job.get('title')}\n"
        f"Location: {job.get('location') or 'n/a'} | Remote: {job.get('remote')}\n"
        f"Posted: {job.get('posted_at') or 'n/a'} | URL: {job.get('url')}\n"
        f"Salary: {job.get('salary_text') or 'n/a'}\n\n"
        f"{truncate(job.get('description') or '(no description available)', 12000)}\n\n"
        "Return the JSON assessment."
    )


COVER_SYSTEM = (
    "You write short, specific, honest cover letters and screening answers for ONE candidate. Never invent "
    "experience, degrees, employers, dates or numbers that are not in the profile. Plain prose, no bullet points, "
    "no clichés like 'I am writing to express my interest'. 160-240 words. Sign off with the candidate's full name "
    "exactly as it appears in the profile facts; if no name is given there, sign '[Your name]'. Ignore any other "
    "identity information you may have about the operator of this tool: only the profile below describes the candidate. "
    "Where the profile lacks something the role needs, write around it rather than inserting bracketed placeholders, "
    "except that one short bracketed note is acceptable when the resume is entirely missing."
)

COVER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "cover_letter": {"type": "string"},
        "short_pitch": {"type": "string", "description": "<= 60 words, for 'why do you want this role' boxes"},
        "subject": {"type": "string"},
    },
    "required": ["cover_letter", "short_pitch"],
    "additionalProperties": False,
}


def build_cover_prompt(profile_text: str, job: dict[str, Any], fit: dict[str, Any] | None) -> str:
    return (
        "## Candidate profile\n"
        f"{truncate(profile_text, 9000)}\n\n"
        "## Job\n"
        f"Company: {job.get('company_name')}\nTitle: {job.get('title')}\nLocation: {job.get('location')}\n\n"
        f"{truncate(job.get('description') or '', 8000)}\n\n"
        "## Earlier assessment (strengths to lean on, gaps to not over-claim)\n"
        f"{json.dumps(fit or {}, ensure_ascii=False)[:2000]}\n\n"
        "Write the cover letter addressed to the hiring team, then the short pitch."
    )


FORM_SYSTEM = (
    "You map job-application form fields to a candidate's known answers. You only use values that are present in "
    "the answer bank, the profile or the prepared cover letter. If a required field has no truthful answer, mark "
    "it 'skip' and list the question under 'unanswered' so a human can fill it. Never guess salary, visa status, "
    "demographics, or dates. For select/radio fields the value MUST be one of the given options, verbatim. For "
    "checkbox_group fields give the option labels to tick, comma-separated, verbatim. Consent/acknowledgement "
    "checkboxes for privacy notices may be ticked ('check' with value 'yes'); demographic surveys are skipped. "
    "Only list a question under 'unanswered' when it is required or clearly important; optional demographic fields "
    "do not belong there."
)

FORM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "plan": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "field_id": {"type": "string"},
                    "action": {"type": "string", "enum": ["fill", "select", "check", "upload_resume", "skip"]},
                    "value": {"type": "string"},
                    "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
                    "reason": {"type": "string"},
                },
                "required": ["field_id", "action", "value", "confidence"],
                "additionalProperties": False,
            },
        },
        "unanswered": {"type": "array", "items": {"type": "string"}},
        "notes": {"type": "string"},
    },
    "required": ["plan", "unanswered"],
    "additionalProperties": False,
}


def build_form_prompt(fields: list[dict[str, Any]], answers: dict[str, str], profile_summary: str,
                      cover_letter: str | None, job: dict[str, Any]) -> str:
    return (
        f"## Job\n{job.get('company_name')} — {job.get('title')}\n\n"
        "## Answer bank (only source of truth for personal facts)\n"
        f"{json.dumps(answers, ensure_ascii=False, indent=1)}\n\n"
        "## Profile summary\n"
        f"{truncate(profile_summary, 3000)}\n\n"
        "## Prepared cover letter (use for 'cover letter' / 'additional information' fields)\n"
        f"{truncate(cover_letter or '', 2500)}\n\n"
        "## Form fields (id, label, type, required, options)\n"
        f"{json.dumps(fields, ensure_ascii=False, indent=1)[:14000]}\n\n"
        "Produce the fill plan. Use action 'upload_resume' for the resume/CV file input."
    )


EXTRACT_SYSTEM = (
    "You extract job listings from the text and links of a careers web page. Return only real job openings "
    "(not navigation, blog posts, or generic 'join us' links). Prefer absolute URLs."
)

EXTRACT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "jobs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "location": {"type": "string"},
                    "url": {"type": "string"},
                    "department": {"type": "string"},
                },
                "required": ["title", "url"],
                "additionalProperties": False,
            },
        },
        "page_kind": {"type": "string", "enum": ["job_list", "single_job", "not_careers", "blocked"]},
        "ats_hint": {"type": "string", "description": "greenhouse/lever/ashby/workable/smartrecruiters/other if visible"},
    },
    "required": ["jobs", "page_kind"],
    "additionalProperties": False,
}


# Links that look like one posting (an id in the URL, a job-detail path) and card links with longer text.
_POSTING = re.compile(r"\d{5,}|jobid|job-?detail|viewjob|/jd/|/j/|/job/|/jobs/[^/?#]*\d", re.I)
_CHROME = re.compile(r"[?&]ref=(top|footer|nav)|/(login|signup|register|pricing|blog|about|help|faq|privacy|terms)(\b|/)", re.I)


def rank_links(links: list[dict[str, str]]) -> list[dict[str, str]]:
    """Job links first. Big sites put hundreds of menu links before the job cards, and the link list is cut to fit
    the prompt, which used to drop every posting link (the AI saw the titles but had no URL to return)."""
    seen: set[str] = set()
    unique = [x for x in links if x.get("href") and not (x["href"] in seen or seen.add(x["href"]))]

    def score(x: dict[str, str]) -> int:
        return 2 * bool(_POSTING.search(x["href"])) + (len(x.get("text", "")) >= 25) - 2 * bool(_CHROME.search(x["href"]))

    return sorted(unique, key=score, reverse=True)       # stable: page order kept within the same score


def build_extract_prompt(page_url: str, text: str, links: list[dict[str, str]]) -> str:
    return (
        f"Page URL: {page_url}\n\n## Visible text\n{truncate(text, 9000)}\n\n"
        f"## Links (text -> href)\n{json.dumps(rank_links(links)[:300], ensure_ascii=False)[:9000]}\n\n"
        "List the job openings on this page."
    )


PROFILE_SYSTEM = (
    "You turn a resume into structured fields. Copy facts exactly as written: company names, titles, dates, degrees, "
    "numbers. Do not invent, infer or embellish facts that are not in the text; leave a field empty when the resume "
    "does not say. Dates stay in the resume's own format (e.g. 'Jan 2024', '2022'). Write 'Present' for an ongoing role. "
    "Two fields are suggestions, not facts, and are always filled. suggested_roles: the job titles this resume is aimed "
    "at, judged from its headline or title line, its objective, the most recent role and the projects. Write them as "
    "employers usually post them (short, e.g. 'AI Engineer', not the resume's own headline), the most common title "
    "first (up to 6, all from the same family of work). Do not add broad fallback titles from a "
    "neighbouring field just because some skills overlap: a resume aimed at AI or ML work gets AI/ML titles, not plain "
    "backend or full-stack ones, unless the resume itself presents the person that way. suggested_title_keywords: short "
    "lowercase words or phrases that appear in the titles of those jobs and set them apart from other jobs, including "
    "the family's short form and close synonyms (for example 'ai', 'llm', 'genai', 'machine learning', 'ml', 'data "
    "scientist'). Never a generic word on its own such as 'engineer', "
    "'developer', 'software', 'senior', 'full' or 'stack'. seniority is your judgement from the experience shown."
)

_STR = {"type": "string"}
PROFILE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "headline": {"type": "string", "description": "one line in normal capitalisation, e.g. 'Backend developer, Python/FastAPI'"},
        "summary": {"type": "string", "description": "4-6 sentence third-person summary"},
        "skills": {"type": "array", "items": _STR, "maxItems": 40},
        "years_experience": {"type": "number", "description": "total professional experience in years (recomputed from the role dates)"},
        "suggested_title_keywords": {"type": "array", "items": _STR, "maxItems": 12},
        "suggested_roles": {"type": "array", "items": _STR, "maxItems": 8},
        "seniority": {"type": "string", "enum": ["intern", "junior", "mid", "senior", "lead"]},
        "experience": {"type": "array", "maxItems": 15, "items": {"type": "object", "properties": {
            "title": _STR, "company": _STR, "location": _STR, "start": _STR, "end": _STR, "employment_type": _STR,
            "highlights": {"type": "array", "items": _STR, "maxItems": 8}},
            "required": ["title", "company", "start", "end", "highlights"], "additionalProperties": False}},
        "education": {"type": "array", "maxItems": 6, "items": {"type": "object", "properties": {
            "institution": _STR, "degree": _STR, "field": _STR, "start": _STR, "end": _STR, "grade": _STR},
            "required": ["institution", "degree"], "additionalProperties": False}},
        "projects": {"type": "array", "maxItems": 10, "items": {"type": "object", "properties": {
            "name": _STR, "summary": _STR, "tech": {"type": "array", "items": _STR, "maxItems": 12}, "link": _STR},
            "required": ["name", "summary"], "additionalProperties": False}},
        "certifications": {"type": "array", "items": _STR, "maxItems": 15},
        "languages": {"type": "array", "items": _STR, "maxItems": 10},
        "contact": {"type": "object", "properties": {
            "full_name": _STR, "email": _STR, "phone": _STR, "location": _STR,
            "linkedin": _STR, "github": _STR, "portfolio": _STR}, "additionalProperties": False},
    },
    "required": ["headline", "summary", "skills", "years_experience", "suggested_roles", "seniority", "experience",
                 "education", "projects", "contact"],
    "additionalProperties": False,
}


def build_profile_prompt(resume_text: str) -> str:
    return f"## Resume\n{truncate(resume_text, 12000)}\n\nReturn the structured summary."
