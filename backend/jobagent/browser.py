"""Playwright helper: one persistent Chromium profile under data/ so logins and cookies survive between runs.

The browser presents itself as what it is (its own user agent and automation flag): no disguise. Sites that refuse
automated visitors are left alone or read slowly (pacing.py), never tricked."""

from __future__ import annotations

import os
import re
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from playwright.sync_api import BrowserContext, Page, sync_playwright

from . import pacing
from .config import get_settings

BLOCK_CHALLENGE_MARKERS = (
    "verify you are human", "checking your browser", "cf-chl", "captcha", "unusual traffic",
    "access denied", "are you a robot", "just a moment",
)


# Installed browsers JobPilot can drive instead of its own Chromium, always with JobPilot's own profile folder (never
# the user's personal profile, and nothing about the system's default browser changes).
CHANNELS: dict[str, dict[str, object]] = {
    "chrome": {"label": "Google Chrome", "paths": ("/Applications/Google Chrome.app", "~/Applications/Google Chrome.app"),
               "bins": ("google-chrome", "google-chrome-stable")},
    "msedge": {"label": "Microsoft Edge", "paths": ("/Applications/Microsoft Edge.app", "~/Applications/Microsoft Edge.app"),
               "bins": ("microsoft-edge", "microsoft-edge-stable")},
}


def channel_installed(channel: str) -> bool:
    c = CHANNELS.get(channel)
    if not c:
        return False
    return any(Path(str(p)).expanduser().exists() for p in c["paths"]) or any(shutil.which(str(b)) for b in c["bins"])


def channel_for_user_agent(user_agent: str) -> str:
    """The installed browser matching the one the user clicked from: Edge or Chrome (Chromium-based browsers that send
    a plain Chrome user agent, such as Brave or Arc, count as Chrome). "" = keep JobPilot's own Chromium."""
    ua = user_agent or ""
    if "Edg/" in ua:
        return "msedge" if channel_installed("msedge") else ""
    if "Chrome/" in ua and not any(x in ua for x in ("OPR/", "SamsungBrowser")):
        return "chrome" if channel_installed("chrome") else ""
    return ""


def current_channel() -> str:
    """The browser JobPilot uses for everything (signing in, reading sites, filling forms): one browser, so the saved
    profile is never opened by an older version than the last one."""
    from .db import session_scope
    from .settings_store import get_setting

    try:
        with session_scope() as db:
            channel = str(get_setting(db, "browser.channel") or "")
    except Exception:          # no database yet (tests, first run)
        return ""
    return channel if channel_installed(channel) else ""


def browser_label() -> str:
    channel = current_channel()
    return str(CHANNELS[channel]["label"]) if channel else "JobPilot's Chromium"


def profile_in_use(profile: Path | None = None) -> bool:
    """True while some browser has JobPilot's profile open (a run reading sites, or a sign-in window): Chromium keeps
    a SingletonLock link to "host-pid" in the folder, and a second browser can't open the same profile."""
    lock = (profile or get_settings().browser_profile_dir) / "SingletonLock"
    if not os.path.lexists(lock):
        return False
    try:
        pid = int(os.readlink(lock).rsplit("-", 1)[-1])
        os.kill(pid, 0)
    except (OSError, ValueError):
        return False           # left behind by a crash: Chromium replaces it
    return True


def sign_out_of(domain: str) -> int:
    """Sign JobPilot out of a site: delete that site's cookies (and its subdomains') from JobPilot's own profile.
    Returns how many were removed. The user's own browsers are never touched. The profile must not be in use."""
    match = re.compile(rf"^\.?([a-z0-9-]+\.)*{re.escape(domain.lower())}$")
    with launch_context(headless=True) as ctx:
        removed = sum(1 for c in ctx.cookies() if match.match(str(c.get("domain", "")).lower()))
        ctx.clear_cookies(domain=match)
    return removed


@contextmanager
def launch_context(headless: bool | None = None, profile: str | None = None) -> Iterator[BrowserContext]:
    s = get_settings()
    if headless is None:
        headless = s.browser_headless
    user_data = s.browser_profile_dir if profile is None else (s.data_dir / profile)
    user_data.mkdir(parents=True, exist_ok=True)
    channel = current_channel()
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(user_data),
            channel=channel or None,
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
