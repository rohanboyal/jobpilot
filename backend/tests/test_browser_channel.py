"""Signing in opens in the browser the user clicked from (when installed), with JobPilot's own profile; a busy profile
or a window that can't start is reported instead of a false "window opened"."""

from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

from jobagent import browser
from jobagent.api import pipeline as api_pipeline
from jobagent.db import session_scope
from jobagent.settings_store import get_setting, set_setting

CHROME_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
             "Chrome/157.0.0.0 Safari/537.36")
EDGE_UA = CHROME_UA + " Edg/157.0.0.0"
SAFARI_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) "
             "Version/19.0 Safari/605.1.15")


@pytest.fixture
def installed(client, monkeypatch):          # client: the database exists
    monkeypatch.setattr(browser, "channel_installed", lambda c: c in ("chrome", "msedge"))
    yield
    with session_scope() as db:
        set_setting(db, "browser.channel", "")


def test_the_clicking_browser_picks_the_channel(installed, monkeypatch):
    assert browser.channel_for_user_agent(CHROME_UA) == "chrome"
    assert browser.channel_for_user_agent(EDGE_UA) == "msedge"
    assert browser.channel_for_user_agent(SAFARI_UA) == ""                 # Safari, Firefox: JobPilot's Chromium
    monkeypatch.setattr(browser, "channel_installed", lambda c: False)
    assert browser.channel_for_user_agent(CHROME_UA) == ""                 # not installed: JobPilot's Chromium


@pytest.mark.skipif(sys.platform == "win32", reason="Chromium uses a symlink lock on macOS and Linux only")
def test_a_live_lock_means_busy_and_a_stale_one_does_not(tmp_path):
    lock = tmp_path / "SingletonLock"
    os.symlink(f"myhost-{os.getpid()}", lock)
    assert browser.profile_in_use(tmp_path)
    lock.unlink()
    os.symlink("myhost-999999", lock)                                      # that process is gone
    assert not browser.profile_in_use(tmp_path)


class _Proc:
    def __init__(self, code: int | None):
        self.code = code

    def wait(self, timeout: float):
        if self.code is None:
            raise subprocess.TimeoutExpired("x", timeout)                  # the window stays open: it started
        return self.code


def test_sign_in_from_chrome_opens_chrome_and_remembers_it(client, installed, monkeypatch):
    monkeypatch.setattr(browser, "profile_in_use", lambda profile=None: False)
    launched: list[list[str]] = []
    monkeypatch.setattr(api_pipeline.subprocess, "Popen", lambda args, **kw: launched.append(args) or _Proc(None))
    r = client.post("/api/pipeline/browser-login?site=https://example.com/login", headers={"User-Agent": CHROME_UA})
    assert r.status_code == 200 and r.json()["browser"] == "Google Chrome", r.text
    assert "separate JobPilot profile" in r.json()["note"] and launched[0][-1] == "https://example.com/login"
    with session_scope() as db:
        assert get_setting(db, "browser.channel") == "chrome"            # reading sites uses Chrome from now on
    # from Safari the choice already made stays: one browser for the saved profile
    client.post("/api/pipeline/browser-login?site=https://example.com/login", headers={"User-Agent": SAFARI_UA})
    with session_scope() as db:
        assert get_setting(db, "browser.channel") == "chrome"


def test_busy_profile_and_failed_start_are_reported(client, installed, monkeypatch):
    monkeypatch.setattr(browser, "profile_in_use", lambda profile=None: True)
    r = client.post("/api/pipeline/browser-login?site=https://example.com/login")
    assert r.status_code == 409 and "busy" in r.json()["detail"]
    monkeypatch.setattr(browser, "profile_in_use", lambda profile=None: False)
    monkeypatch.setattr(api_pipeline.subprocess, "Popen", lambda args, **kw: _Proc(1))
    r = client.post("/api/pipeline/browser-login?site=https://example.com/login")
    assert r.status_code == 502 and "could not open" in r.json()["detail"]


def test_sign_out_removes_only_that_sites_cookies_from_jobpilots_profile(client):
    from jobagent.browser import launch_context, sign_out_of

    # saved logins outlive the browser ("keep me signed in"): give them an expiry, as sites do
    with launch_context(headless=True) as ctx:
        ctx.add_cookies([
            {"name": "session", "value": "a", "expires": time.time() + 86400, "domain": "wellfound.com", "path": "/"},
            {"name": "auth", "value": "b", "expires": time.time() + 86400, "domain": ".api.wellfound.com", "path": "/"},
            {"name": "keep", "value": "c", "expires": time.time() + 86400, "domain": "example.com", "path": "/"},
        ])
    assert sign_out_of("wellfound.com") == 2
    with launch_context(headless=True) as ctx:
        left = {c["domain"] for c in ctx.cookies()}
    assert "example.com" in left and not any("wellfound" in d for d in left)


def test_sign_out_endpoint(client, monkeypatch):
    from jobagent import pacing

    with session_scope() as db:
        pacing.mark_signed_in(db, "site_wellfound")
    monkeypatch.setattr(browser, "profile_in_use", lambda profile=None: True)
    assert client.delete("/api/pipeline/browser-login?site=site_wellfound").status_code == 409   # busy: still signed in
    monkeypatch.setattr(browser, "profile_in_use", lambda profile=None: False)
    monkeypatch.setattr(browser, "sign_out_of", lambda domain: 3)
    r = client.delete("/api/pipeline/browser-login?site=site_wellfound").json()
    assert r == {"ok": True, "domain": "wellfound.com", "removed": 3}
    with session_scope() as db:
        assert "site_wellfound" not in pacing.signed_in_sites(db)
