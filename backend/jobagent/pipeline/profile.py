"""Resumes (row 1 is the default; each search profile may pick another) and the candidate text used in prompts."""

from __future__ import annotations

import re
import shutil
import zipfile
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings, load_answer_bank
from ..llm.client import run_llm
from ..llm.prompts import PROFILE_SCHEMA, PROFILE_SYSTEM, build_profile_prompt
from ..models import Application, Job, Profile, SearchProfileRow, utcnow
from ..profiles import clean_title_keywords


def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        return "\n".join((p.extract_text() or "") for p in reader.pages).strip()
    if suffix == ".docx":
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml").decode("utf-8", "ignore")
        xml = re.sub(r"</w:p>", "\n", xml)
        return re.sub(r"<[^>]+>", "", xml).strip()
    return path.read_text(encoding="utf-8", errors="ignore").strip()


def _free_dest(db: Session, base: Path, own_id: int) -> Path:
    """`base`, or base-2, base-3... when another resume or any application points to that file: a sent application's
    file is part of its record, and a deleted resume's id (and so its file name) can come back."""
    taken = set(db.scalars(select(Profile.resume_path).where(Profile.id != own_id, Profile.resume_path.is_not(None))))
    taken |= set(db.scalars(select(Application.resume_path).where(Application.resume_path.is_not(None))))
    dest, n = base, 2
    while str(dest) in taken:
        dest, n = base.with_name(f"{base.stem}-{n}{base.suffix}"), n + 1
    return dest


def import_resume(db: Session, src: Path, original_name: str | None = None, resume_id: int | None = 1,
                  name: str | None = None) -> Profile:
    """Store a resume file and its text: into resume `resume_id` (1 = the default), or a new resume when None."""
    s = get_settings()
    original_name = original_name or src.name
    text = extract_text(src)
    if len(text) < 100:
        raise ValueError("Could not extract readable text from the resume (scanned PDF?). Paste the text instead.")
    p = db.get(Profile, resume_id) if resume_id else None
    if p is None:
        p = Profile(id=resume_id) if resume_id == 1 else Profile()
        db.add(p)
        db.flush()
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", original_name)
    dest = _free_dest(db, s.resume_dir / (safe if p.id == 1 else f"r{p.id}-{safe}"), p.id)
    if src.resolve() != dest.resolve():
        shutil.copyfile(src, dest)
    if name or not p.name:
        p.name = (name or Path(original_name).stem.replace("_", " ")).strip()[:120]
    p.resume_text = text
    p.resume_path = str(dest)
    p.extra = {**(p.extra or {}), "resume_uploaded_at": utcnow().isoformat()}
    p.resume_filename = original_name
    p.updated_at = utcnow()
    db.add(p)
    db.commit()
    return p


_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
_ONGOING = re.compile(r"^(present|current|now|ongoing|till date|to date|today)", re.I)
_INTERN = re.compile(r"\b(intern|internship|trainee|apprentice)\b", re.I)


def _when(text: str | None, today: date, end: bool) -> date | None:
    """'Oct 2025', 'October 2025', '10/2025', '2025-10', '2025' or 'Present' as a date. An end date means the end of
    that month (or year)."""
    s = (text or "").strip().lower()
    if _ONGOING.match(s):
        return today
    year = month = None
    if m := re.search(r"([a-z]{3})[a-z]*\.?\s*'?(\d{4}|\d{2})\b", s):
        if m.group(1) in _MONTHS:
            month, year = _MONTHS[m.group(1)], int(m.group(2)) + (2000 if len(m.group(2)) == 2 else 0)
    if year is None and (m := re.search(r"\b(\d{1,2})[/.-](\d{4})\b", s)):
        month, year = int(m.group(1)), int(m.group(2))
    if year is None and (m := re.search(r"\b(\d{4})[/.-](\d{1,2})\b", s)):
        year, month = int(m.group(1)), int(m.group(2))
    if year is None and (m := re.search(r"\b(19|20)\d{2}\b", s)):
        year = int(m.group(0))
    if year is None or not (month or 1) <= 12:
        return None
    if not end:
        return date(year, month or 1, 1)
    last = date(year + 1, 1, 1) if (month or 12) == 12 else date(year, month + 1, 1)
    return min(last, today)


def years_from_experience(experience: list[dict] | None, today: date | None = None) -> float | None:
    """Years of work the roles' own dates add up to: overlaps count once, internships only when there is nothing
    else. None when no role has readable dates. A fact from the resume, unlike a model's estimate."""
    today = today or date.today()
    spans = []
    for e in experience or []:
        start, end = _when(e.get("start"), today, end=False), _when(e.get("end"), today, end=True)
        if start and end and end > start:
            spans.append((start, end, bool(_INTERN.search(e.get("title") or ""))))
    if not spans:
        return None
    work = [(s, e) for s, e, intern in spans if not intern] or [(s, e) for s, e, _ in spans]
    total, cur = timedelta(0), None
    for s, e in sorted(work):
        if cur and s <= cur[1]:
            cur = (cur[0], max(cur[1], e))
            continue
        if cur:
            total += cur[1] - cur[0]
        cur = (s, e)
    total += cur[1] - cur[0]
    return round(total.days / 365.25, 1)


def analyze_profile(db: Session, resume_id: int = 1) -> dict:
    p = db.get(Profile, resume_id)
    if not p or not (p.resume_text or "").strip():
        raise ValueError("No resume text yet. Upload a resume or paste its text first.")
    result = run_llm(build_profile_prompt(p.resume_text), purpose="profile", schema=PROFILE_SCHEMA,
                        system=PROFILE_SYSTEM, db=db)
    p.headline = result.get("headline") or p.headline
    p.summary = result.get("summary") or p.summary
    p.skills = result.get("skills") or p.skills
    # The model is told not to infer, so a resume that never states its total gets 0: count the role dates instead.
    dated = years_from_experience(result.get("experience"))
    if dated is not None:
        result["years_experience"] = dated
    p.years_experience = result.get("years_experience", p.years_experience)
    p.extra = {**(p.extra or {}), "suggested_roles": result.get("suggested_roles"),
               "suggested_title_keywords": clean_title_keywords(result.get("suggested_title_keywords") or []),
               "seniority": result.get("seniority"),
               **{k: result.get(k) or ([] if k != "contact" else {})
                  for k in ("experience", "education", "projects", "certifications", "languages", "contact")}}
    db.commit()
    return result


def resume_row(db: Session, resume_id: int | None = None) -> Profile | None:
    """That resume if it has text, else the default one (row 1)."""
    p = db.get(Profile, resume_id) if resume_id else None
    if p is not None and (p.resume_text or p.summary or "").strip():
        return p
    return db.get(Profile, 1)


def resume_for_profile(db: Session, search_profile_id: int | None) -> Profile | None:
    row = db.get(SearchProfileRow, search_profile_id) if search_profile_id else None
    return resume_row(db, row.resume_id if row else None)


def resume_for_job(db: Session, job: Job, among: list[int] | None = None) -> Profile | None:
    """The resume of the profile the job is judged against."""
    from ..profiles import pick_profile

    return resume_for_profile(db, pick_profile(db, job.profile_ids, among)[0])


def profile_text(db: Session, resume_id: int | None = None) -> str:
    """What the AI sees as 'the candidate': resume text, else summary + answer bank basics."""
    p = resume_row(db, resume_id)
    parts: list[str] = []
    if p:
        if p.headline:
            parts.append(f"Headline: {p.headline}")
        if p.resume_text:
            parts.append(p.resume_text)
        elif p.summary:
            parts.append(p.summary)
        if p.skills:
            parts.append("Skills: " + ", ".join(p.skills))
        if p.years_experience is not None:
            parts.append(f"Years of experience: {p.years_experience}")
    bank = load_answer_bank()
    basics = {k: v for k, v in {**bank.identity, **bank.eligibility}.items() if v and k not in ("phone", "email")}
    if basics:
        parts.append("Facts: " + "; ".join(f"{k}={v}" for k, v in basics.items()))
    return "\n\n".join(parts)
