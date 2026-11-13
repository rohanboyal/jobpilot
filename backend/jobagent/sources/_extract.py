"""AI-assisted extraction of job listings from arbitrary careers pages (used by browser adapters)."""

from __future__ import annotations

from urllib.parse import urljoin

from playwright.sync_api import Page

from ..browser import dismiss_cookie_banners, looks_blocked, page_text_and_links
from ..llm.client import run_llm
from ..llm.prompts import EXTRACT_SCHEMA, EXTRACT_SYSTEM, build_extract_prompt
from .base import SourceContext


def scroll_a_bit(page: Page, steps: int = 4) -> None:
    for _ in range(steps):
        try:
            page.mouse.wheel(0, 1600)
            page.wait_for_timeout(500)
        except Exception:
            break


def extract_listings(ctx: SourceContext, page: Page, url: str) -> dict:
    """Open `url` in `page`, let the AI read it, return {'jobs': [...], 'page_kind': ..., 'ats_hint': ...}."""
    if page.url != url:          # callers often have it open already; loading it twice helps nobody
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)
    dismiss_cookie_banners(page)
    if looks_blocked(page):
        ctx.bump("blocked")
        return {"jobs": [], "page_kind": "blocked"}
    scroll_a_bit(page)
    text, links = page_text_and_links(page)
    if len(text.strip()) < 80:
        return {"jobs": [], "page_kind": "not_careers"}
    result = run_llm(build_extract_prompt(url, text, links), purpose="extract", schema=EXTRACT_SCHEMA,
                        system=EXTRACT_SYSTEM, db=ctx.db)
    jobs = []
    for j in result.get("jobs", []):
        href = (j.get("url") or "").strip()
        if not href or not j.get("title"):
            continue
        j["url"] = urljoin(url, href)
        jobs.append(j)
    result["jobs"] = jobs
    return result


def read_job_page(page: Page, url: str, max_chars: int = 15000) -> str:
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(1000)
    dismiss_cookie_banners(page)
    if looks_blocked(page):
        return ""
    try:
        main = page.locator("main, article, [role=main], #jobDescriptionText, .job-description, .posting").first
        if main.count() and main.is_visible():
            txt = main.inner_text(timeout=5000)
            if len(txt) > 200:
                return txt[:max_chars]
    except Exception:
        pass
    try:
        return page.locator("body").inner_text(timeout=8000)[:max_chars]
    except Exception:
        return ""
