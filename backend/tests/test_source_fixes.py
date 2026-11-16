"""Sources that broke on a real run: Levels.fyi's per-minute limit, company boards that no longer exist, The Muse."""

from __future__ import annotations

from jobagent.models import Company
from jobagent.sources import levelsfyi
from jobagent.sources.base import ATSSource, SourceContext
from jobagent.sources.themuse import TheMuse
from jobagent.utils.http import HttpError


def test_levels_fyi_waits_when_told_and_keeps_its_calls_spaced(monkeypatch):
    sleeps: list[float] = []
    clock = [1000.0]
    monkeypatch.setattr(levelsfyi.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(levelsfyi.time, "sleep", lambda s: sleeps.append(s) or clock.__setitem__(0, clock[0] + s))
    replies = iter([RuntimeError("Levels.fyi MCP error: Error: You've hit the free limit of 20 calls per minute. "
                                 "Try again in 33 seconds (retryAfterSeconds: 33)."), {"jobs": [1]}, {"jobs": [2]}])

    def fake(client, name, args):
        r = next(replies)
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(levelsfyi, "_call", fake)
    levelsfyi._last_call[0] = 0.0
    assert levelsfyi.call_tool(None, "search-jobs", {}) == {"jobs": [1]}       # waited 34s once, then went on
    assert 34 in sleeps
    sleeps.clear()
    assert levelsfyi.call_tool(None, "search-jobs", {}) == {"jobs": [2]}
    assert sleeps and abs(sleeps[0] - levelsfyi._MIN_GAP_S) < 0.01               # the next call keeps its distance


class _Board(ATSSource):
    name, label, ats_type = "test_board", "Test board", "testats"

    def fetch_company(self, ctx, company):
        if company.ats_slug == "gone":
            raise HttpError(404, f"https://boards.test/{company.ats_slug}")
        if company.ats_slug == "flaky":
            raise HttpError(503, f"https://boards.test/{company.ats_slug}")
        return []


def test_a_company_board_that_no_longer_exists_is_paused_with_a_note():
    gone = Company(name="Gone Co", ats_type="testats", ats_slug="gone", is_active=True)
    flaky = Company(name="Flaky Co", ats_type="testats", ats_slug="flaky", is_active=True)
    ctx = SourceContext(settings=None, search=None, db=None, log=lambda m: None, companies=[gone, flaky])
    list(_Board().fetch(ctx))
    assert gone.is_active is False and "was not found (404)" in gone.notes
    assert flaky.is_active is True                       # a server hiccup is not a missing board


def test_the_muse_is_off_by_default_while_its_api_is_behind_a_bot_check():
    assert TheMuse.default_enabled is False and TheMuse.fragile is True
