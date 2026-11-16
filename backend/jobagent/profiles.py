"""Search profiles: several kinds of job the user wants, each with its own roles, keywords, places and thresholds.

Crawling uses the *merged* profile (union of the profiles in the run) so each board is searched once; its job titles
alternate between profiles, so every profile's top title is searched. The free prefilter then checks every job against
each profile separately and records which ones it matched in `Job.profile_ids`; scoring uses the best-matching
profile's preferences, fit threshold and resume. A run may cover only some profiles (the Run dialog's checkboxes).
"""

from __future__ import annotations

import re
from itertools import zip_longest
from typing import Any

from sqlalchemy import TextClause, bindparam, select, text
from sqlalchemy.orm import Session

from .config import SearchProfile, load_search_profile
from .db import session_scope
from .models import SearchProfileRow

_LIST_FIELDS = ("roles", "title_keywords", "exclude_keywords", "skills", "locations", "countries", "seniority", "job_types")


def ensure_seeded(db: Session) -> bool:
    """First run: turn config/search.yaml into the first profile. Returns True when it created one."""
    if db.scalars(select(SearchProfileRow.id).limit(1)).first() is not None:
        return False
    sp = load_search_profile()
    name = sp.roles[0] if sp.roles else "My search"
    db.add(SearchProfileRow(name=f"{name} (from search.yaml)", enabled=True, data=sp.model_dump()))
    db.commit()
    return True


def rows(db: Session, enabled_only: bool = False) -> list[SearchProfileRow]:
    ensure_seeded(db)
    stmt = select(SearchProfileRow).order_by(SearchProfileRow.id)
    if enabled_only:
        stmt = stmt.where(SearchProfileRow.enabled.is_(True))
    return list(db.scalars(stmt).all())


def to_search(row: SearchProfileRow) -> SearchProfile:
    return SearchProfile.model_validate(row.data or {})


def enabled_profiles(db: Session, ids: list[int] | None = None) -> list[tuple[int, SearchProfile]]:
    """Profiles used for crawling and matching (only `ids` when given). One with no job titles and no title keywords
    (a just-added profile) isn't a search yet: it would match every title and send them all to the AI."""
    out = [(r.id, to_search(r)) for r in rows(db, enabled_only=True) if ids is None or r.id in ids]
    return [(i, s) for i, s in out if any(x.strip() for x in s.roles + s.title_keywords)]


def matches_any(ids: list[int]) -> TextClause:
    """SQL condition: the job matched at least one of these profiles."""
    return text("EXISTS (SELECT 1 FROM json_each(jobs.profile_ids) WHERE json_each.value IN :pids)").bindparams(
        bindparam("pids", value=list(ids), expanding=True))


def merge(profiles: list[SearchProfile]) -> SearchProfile:
    """Union of several profiles, used to decide what to crawl. Order is kept so the first profile's roles lead."""
    if not profiles:
        return load_search_profile()
    if len(profiles) == 1:
        return profiles[0]
    data: dict[str, Any] = {}
    for field in _LIST_FIELDS:
        seen: dict[str, str] = {}
        # Job titles take turns (first of each profile, then the second ...): sources search only the first few.
        values = ([v for group in zip_longest(*(p.roles for p in profiles)) for v in group if v] if field == "roles"
                  else [v for p in profiles for v in getattr(p, field)])
        for v in values:
                if v.strip() and v.strip().lower() not in seen:
                    seen[v.strip().lower()] = v.strip()
        data[field] = list(seen.values())
    # A keyword excluded by one profile may be wanted by another: only keep exclusions every profile shares.
    shared = set.intersection(*[{x.strip().lower() for x in p.exclude_keywords if x.strip()} for p in profiles])
    data["exclude_keywords"] = [x for x in data["exclude_keywords"] if x.lower() in shared]
    data["remote_ok"] = any(p.remote_ok for p in profiles)
    data["onsite_ok"] = any(p.onsite_ok for p in profiles)
    data["hybrid_ok"] = any(p.hybrid_ok for p in profiles)
    if any(not p.job_types for p in profiles):
        data["job_types"] = []
    data["max_age_days"] = max(p.max_age_days for p in profiles)
    data["min_prefilter_score"] = min(p.min_prefilter_score for p in profiles)
    data["min_fit_score"] = min(p.min_fit_score for p in profiles)
    return SearchProfile.model_validate(data)


def active_search(db: Session | None = None, ids: list[int] | None = None) -> SearchProfile:
    """The merged profile of everything enabled, or of `ids` (what sources search for)."""
    if db is not None:
        return merge([p for _, p in enabled_profiles(db, ids)])
    with session_scope() as d:
        return merge([p for _, p in enabled_profiles(d, ids)])


def pick_profile(db: Session, profile_ids: list[int] | None,
                 among: list[int] | None = None) -> tuple[int | None, SearchProfile]:
    """The profile a job is judged against: the first one it matched (of `among`, when a run covers only some
    profiles), else the merged profile (id None)."""
    profiles = dict(enabled_profiles(db))
    for pid in profile_ids or []:
        if pid in profiles and (among is None or pid in among):
            return pid, profiles[pid]
    return None, merge(list(profiles.values()))


def profile_for_job(db: Session, profile_ids: list[int] | None) -> SearchProfile:
    return pick_profile(db, profile_ids)[1]


def names(db: Session, ids: list[int] | None) -> str:
    """'Data Scientist, Applied AI' for log lines and task labels; 'all profiles' when ids is None."""
    if ids is None:
        return "all profiles"
    by_id = {r.id: r.name for r in rows(db)}
    return ", ".join(by_id.get(i, f"#{i}") for i in ids)


# Words that are in nearly every job title: on their own they would let every job through the title check.
GENERIC_TITLE_WORDS = frozenset({
    "engineer", "engineers", "engineering", "developer", "developers", "development", "software", "senior", "sr",
    "junior", "jr", "lead", "staff", "principal", "intern", "internship", "full", "stack", "specialist", "associate",
    "manager", "consultant", "analyst", "architect", "programmer", "applied", "artificial", "intelligence", "remote",
    "the", "and", "of", "for", "with", "i", "ii", "iii",
})


def clean_title_keywords(words: list[str]) -> list[str]:
    """Title keywords that actually narrow the search: lowercase, de-duplicated, no generic single words.
    "artificial intelligence" (a phrase) stays; "intelligence" alone would also match "Business Intelligence"."""
    out: list[str] = []
    for w in words:
        k = " ".join(str(w).lower().split())
        if k and k not in GENERIC_TITLE_WORDS and k not in out:
            out.append(k)
    return out


def from_resume_analysis(analysis: dict[str, Any], base: SearchProfile | None = None) -> SearchProfile:
    """A first profile built from the AI's resume analysis, keeping places and thresholds from `base`."""
    base = base or load_search_profile()
    data = base.model_dump()
    if analysis.get("suggested_roles"):
        data["roles"] = analysis["suggested_roles"][:6]
    if analysis.get("suggested_title_keywords") or analysis.get("suggested_roles"):
        # Acronyms in the suggested titles (AI, LLM, ML, NLP…) are the surest sign of the kind of job: always keep them.
        acronyms = [w for r in analysis.get("suggested_roles") or [] for w in re.findall(r"\b[A-Z]{2,4}\b", r)]
        data["title_keywords"] = clean_title_keywords([*acronyms, *(analysis.get("suggested_title_keywords") or [])])[:12]
    if analysis.get("skills"):
        data["skills"] = [s.lower() for s in analysis["skills"][:20]]
    years = analysis.get("years_experience")
    if isinstance(years, int | float):
        data["experience_max"] = float(int(years) + 2)      # roles asking up to ~2 years more than you have
    seniority = analysis.get("seniority")
    if seniority in ("intern", "junior"):
        data["seniority"] = ["junior"]
    elif seniority == "mid":
        data["seniority"] = ["junior", "mid"]
    elif seniority in ("senior", "lead"):
        data["seniority"] = ["mid", "senior"]
        data["exclude_keywords"] = [x for x in data["exclude_keywords"] if x.strip().lower() not in ("staff engineer", "principal")]
    return SearchProfile.model_validate(data)
