"""Free, rule-based facts read from a posting: experience required, work mode, job type and salary.

Each reader returns None when the posting does not say. Filters treat "unknown" as a pass, so a vague posting is
never hidden for something it did not state.
"""

from __future__ import annotations

import re
from typing import Any

_NUM = r"(\d{1,2}(?:\.\d)?)"
_YRS = r"(?:years?|yrs?)"
# "3-5 years", "3 to 5 yrs", "2+ years", "minimum 4 years", "at least 3 years" — only near the word "experience"
_RANGE = re.compile(rf"{_NUM}\s*\+?\s*(?:-|–|—|to)\s*{_NUM}\s*\+?\s*{_YRS}", re.I)
_PLUS = re.compile(rf"(?:minimum(?:\s+of)?|at\s+least|min\.?)?\s*{_NUM}\s*(\+|plus)?\s*{_YRS}", re.I)
_FRESHER = re.compile(r"\b(fresher|freshers|entry[- ]level|new grad(?:uate)?|graduate (?:role|program)|0\s*-\s*1\s*years?)\b", re.I)


_AFTER = re.compile(r"^[^.!?\n;]{0,40}?\b(experience|exp)\b", re.I)
_BEFORE = re.compile(r"\b(experience|exp)\b(?:\s*(?:of|:|-|–|required|needed|level|minimum|min\.?|at least))*\s*$", re.I)


def _about_experience(t: str, start: int, end: int) -> bool:
    """The number must be part of an experience phrase: '3 years of experience', 'Experience: 3-5 yrs'."""
    return bool(_AFTER.search(t[end:end + 60]) or _BEFORE.search(t[max(0, start - 30):start]))


def parse_experience(*texts: str | None) -> tuple[float, float | None] | None:
    """Smallest experience requirement stated as an experience phrase: (min, max or None). None when not stated."""
    for text in texts:
        if not text:
            continue
        t = text[:20000]
        best: tuple[float, float | None] | None = None
        for m in _RANGE.finditer(t):
            if not _about_experience(t, m.start(), m.end()):
                continue
            lo, hi = float(m.group(1)), float(m.group(2))
            if lo <= hi <= 30 and (best is None or lo < best[0]):
                best = (lo, hi)
        if best is None:
            for m in _PLUS.finditer(t):
                if not _about_experience(t, m.start(), m.end()):
                    continue
                lo = float(m.group(1))
                if lo <= 30 and (best is None or lo < best[0]):
                    best = (lo, None)
        if best is None and _FRESHER.search(t[:4000]):
            best = (0.0, 1.0)
        if best is not None:
            return best
    return None


_HYBRID = re.compile(r"\bhybrid\b", re.I)
_REMOTE = re.compile(r"\b(remote|work from home|wfh|anywhere|distributed)\b", re.I)
_ONSITE = re.compile(r"\b(on-?site|in-?office|work from office|wfo)\b", re.I)


def work_mode(title: str | None, location: str | None, remote: bool | None, description: str | None) -> str | None:
    """'remote' | 'hybrid' | 'onsite' | None."""
    head = f"{title or ''} {location or ''}"
    if _HYBRID.search(head):
        return "hybrid"
    if remote is True or _REMOTE.search(head):
        return "remote"
    if _ONSITE.search(head):
        return "onsite"
    body = (description or "")[:1500]
    if _HYBRID.search(body):
        return "hybrid"
    if remote is False:
        return "onsite"
    if _ONSITE.search(body):
        return "onsite"
    return None


_TYPES: list[tuple[str, re.Pattern[str]]] = [
    ("internship", re.compile(r"\bintern(ship)?s?\b", re.I)),
    ("freelance", re.compile(r"\b(freelance|freelancer|gig)\b", re.I)),
    ("contract", re.compile(r"\b(contract|contractor|c2c|temporary|fixed[- ]term)\b", re.I)),
    ("part_time", re.compile(r"\bpart[- ]?time\b", re.I)),
    ("full_time", re.compile(r"\b(full[- ]?time|permanent|fulltime)\b", re.I)),
]


def job_type(title: str | None, employment_type: str | None, description: str | None) -> str | None:
    """'full_time' | 'part_time' | 'contract' | 'internship' | 'freelance' | None."""
    for text in (employment_type, title):
        if text:
            for name, pat in _TYPES:
                if pat.search(text):
                    return name
    head = (description or "")[:1200]
    for name, pat in _TYPES:
        if name != "internship" and pat.search(head):    # "internship" in body text is often about perks
            return name
    return None


_LPA = re.compile(r"(\d+(?:\.\d+)?)\s*(?:-|–|to)?\s*(\d+(?:\.\d+)?)?\s*(?:lpa|lakhs?(?:\s*per\s*annum)?|l\b)", re.I)
# The k/m multiplier must stand alone, so the "m" of "5000 monthly" is not read as million.
_MONEY = re.compile(r"(₹|rs\.?|inr|\$|usd|us\$|€|eur|£|gbp)?\s*(\d[\d,]*(?:\.\d+)?)\s*(?:(k|m)(?![a-z]))?", re.I)
_PER = re.compile(r"per\s*(hour|hr|day|week|wk|month|mo|year|yr|annum)|/\s*(hour|hr|day|week|wk|month|mo|year|yr)|"
                  r"\b(hourly|daily|weekly|monthly|annual|yearly)\b", re.I)
_PER_PIECE = re.compile(r"(?:per|/)\s*(?:task|project|word|article|piece|call|lesson|session|post|video)\b", re.I)
_FACTOR = {"hour": 2080, "hr": 2080, "hourly": 2080, "day": 260, "daily": 260, "week": 52, "wk": 52, "weekly": 52,
           "month": 12, "mo": 12, "monthly": 12}


def parse_salary(text: str | None) -> dict[str, Any] | None:
    """{'currency': 'INR'|'USD'|'EUR'|'GBP', 'min': annual, 'max': annual} from a salary line, or None."""
    if not text:
        return None
    t = text.strip()
    if _PER_PIECE.search(t):          # piece-rate pay is not a salary
        return None
    m = _LPA.search(t)
    if m and re.search(r"lpa|lakh", t, re.I):
        lo = float(m.group(1)) * 100_000
        hi = float(m.group(2)) * 100_000 if m.group(2) else lo
        return {"currency": "INR", "min": lo, "max": max(lo, hi)}
    nums: list[float] = []
    currency = None
    for mm in _MONEY.finditer(t):
        sym, val, mult = mm.group(1), mm.group(2), mm.group(3)
        try:
            v = float(val.replace(",", ""))
        except ValueError:
            continue
        if mult and mult.lower() == "k":
            v *= 1_000
        elif mult and mult.lower() == "m":
            v *= 1_000_000
        if v < 10:
            continue
        nums.append(v)
        if sym and not currency:
            s = sym.lower()
            currency = ("INR" if s in ("₹", "rs", "rs.", "inr") else "EUR" if s in ("€", "eur")
                        else "GBP" if s in ("£", "gbp") else "USD")
    if not nums:
        return None
    if currency is None:
        currency = "INR" if re.search(r"\binr\b|₹|rupee", t, re.I) else "USD" if re.search(r"\busd\b|\$", t, re.I) else None
    if currency is None:
        return None
    per = _PER.search(t)
    unit = (per.group(1) or per.group(2) or per.group(3) or "").lower() if per else ""
    if not unit and max(nums[:2]) < 1_000:      # "$230 - $350" with no unit: a day rate or commission, not a salary
        return None
    factor = _FACTOR.get(unit, 1)
    if factor > 12 and max(nums[:2]) >= 10_000:      # "$60K-$70K, paid hourly": the amounts are already annual
        factor = 1
    lo, hi = min(nums[:2]) * factor, max(nums[:2]) * factor
    return {"currency": currency, "min": lo, "max": hi}


def annotate(job: Any) -> None:
    """Fill the derived columns on a Job row (cheap; safe to call again)."""
    raw = job.raw or {}
    years = raw.get("years") if isinstance(raw, dict) else None
    exp = None
    if isinstance(years, dict) and years.get("min") is not None:     # Geektrust gives it structured
        exp = (float(years["min"]), float(years["max"]) if years.get("max") is not None else None)
    else:
        exp = parse_experience(job.title, job.description)
    job.exp_min, job.exp_max = (exp if exp else (None, None))
    if (job.source or "").startswith("site_"):
        # Browser-read pages include the site's own menus ("Remote jobs"), so only the title and location count.
        job.remote = True if _REMOTE.search(f"{job.title or ''} {job.location or ''}") else None
    job.work_mode = work_mode(job.title, job.location, job.remote, job.description)
    job.job_type = job_type(job.title, job.employment_type, job.description)
    sal = parse_salary(job.salary_text)
    job.salary_currency = sal["currency"] if sal else None
    job.salary_min = sal["min"] if sal else None
    job.salary_max = sal["max"] if sal else None
