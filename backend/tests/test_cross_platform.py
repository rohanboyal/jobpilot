"""Behaviour that differs between macOS, Linux and Windows: process checks, the browser profile lock, prompts on stdin."""

from __future__ import annotations

import subprocess
import sys

from jobagent.browser import launch_context, profile_in_use
from jobagent.utils.proc import pid_alive


def test_checking_a_process_never_ends_it():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        assert pid_alive(child.pid) and pid_alive(child.pid)       # twice: a check must not stop it (Windows!)
        assert child.poll() is None
    finally:
        child.kill()
        child.wait()
    assert not pid_alive(child.pid)
    assert not pid_alive(0) and not pid_alive(None)


def test_the_profile_is_busy_exactly_while_a_browser_has_it_open(client):
    from jobagent.config import get_settings

    profile = get_settings().browser_profile_dir
    with launch_context(headless=True):
        assert profile_in_use(profile)            # macOS/Linux: SingletonLock; Windows: the locked "lockfile"
    assert not profile_in_use(profile)
