"""Playwright helper: one persistent Chromium profile under data/ so logins and cookies survive between runs.

The browser presents itself as what it is (Playwright's Chromium, with its own user agent and automation flag): no
disguise. Sites that refuse automated visitors are left alone or read slowly (pacing.py), never tricked."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from playwright.sync_api import BrowserContext, Page, sync_playwright

from . import pacing
from .config import get_settings

BLOCK_CHALLENGE_MARKERS = (
    "verify you are human", "checking your browser", "cf-chl", "captcha", "unusual traffic",
    "access denied", "are you a robot", "just a moment",
)


@contextmanager
def launch_context(headless: bool | None = None, profile: str | None = None) -> Iterator[BrowserContext]:
    s = get_settings()
    if headless is None:
        headless = s.browser_headless
    user_data = s.browser_profile_dir if profile is None else (s.data_dir / profile)
    user_data.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(user_data),
            headless=headless,
            slow_mo=s.browser_slow_mo_ms or None,
            viewport={"width": 1366, "height": 900},
            locale="en-US",
        )
        try:
            yield ctx
        finally:
            ctx.close()


def new_page(ctx: BrowserContext) -> Page:
    page = ctx.new_page()
    page.set_default_timeout(25_000)
    if pacing.active():
        pacing.attach(page)
    return page


def looks_blocked(page: Page) -> bool:
    try:
        title = (page.title() or "").lower()
        body = page.locator("body").inner_text(timeout=3000).lower()[:4000]
    except Exception:
        return False
    text = title + " " + body
    blocked = any(m in text for m in BLOCK_CHALLENGE_MARKERS) and len(body) < 3000
    if blocked:
        pacing.note_refused("bot check")
    return blocked


def dismiss_cookie_banners(page: Page) -> None:
    for sel in (
        "button:has-text('Accept all')", "button:has-text('Accept All')", "button:has-text('Accept')",
        "button:has-text('I agree')", "button:has-text('Got it')", "#onetrust-accept-btn-handler",
        "button:has-text('Allow all')",
    ):
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=600):
                btn.click(timeout=1500)
                page.wait_for_timeout(300)
                return
        except Exception:
            continue


def page_text_and_links(page: Page, max_links: int = 400) -> tuple[str, list[dict[str, str]]]:
    text = page.locator("body").inner_text(timeout=10_000)
    # A link with no text of its own (an icon, an empty overlay on a job card) takes its label or its card's heading,
    # otherwise job-card links on some sites never reach the AI.
    links = page.evaluate(
        """(max) => Array.from(document.querySelectorAll('a[href]')).slice(0, max).map(a => {
              let text = (a.innerText || a.textContent || '').trim() || a.getAttribute('aria-label') || a.title || '';
              if (!text) {
                const card = a.closest('li, article, div');
                const h = card && card.querySelector('h1, h2, h3, h4, [class*=title i]');
                text = h ? (h.innerText || '').trim() : '';
              }
              return { text: text.slice(0, 120), href: a.href };
            })
             .filter(l => l.text && l.href && !l.href.startsWith('javascript:'))"""
        , max_links)
    return text, links
