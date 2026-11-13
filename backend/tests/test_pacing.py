"""Sites the user signed in to are read slowly and left alone after a refusal; every other source keeps its speed."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterable
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from jobagent import cancel, pacing
from jobagent.browser import launch_context, new_page
from jobagent.config import SearchProfile, get_settings
from jobagent.db import session_scope
from jobagent.health import source_health
from jobagent.models import Run, utcnow
from jobagent.pipeline.ingest import run_source
from jobagent.sources.base import _REGISTRY, RawJob, Source, SourceContext

_BODY = "This role builds backend services in Python with a small team. " * 8
_LIST = ("<html><body><ul>"
         "<li class=job><a href='/job/1'>Backend Engineer</a><span class=co>Acme</span><span class=loc>Pune</span></li>"
         "<li class=job><a href='/job/2'>Python Engineer</a><span class=co>Beta</span><span class=loc>Pune</span></li>"
         "</ul>" + "Search results for your query on this job site. " * 4 + "</body></html>")


@pytest.fixture
def site():
    hits: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            status, html = 200, _LIST
            if self.path.startswith("/forbidden"):
                status, html = 403, "<html><body>no</body></html>"
            elif self.path.startswith("/job/"):
                html = f"<html><body><main>{_BODY}</main></body></html>"
            data = html.encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    server.hits = hits
    server.url = f"http://127.0.0.1:{server.server_port}"
    yield server
    server.shutdown()


@pytest.fixture
def no_waiting(monkeypatch):
    waits: list[float] = []
    monkeypatch.setattr(pacing, "_wait", lambda s, sleep=None: waits.append(s))
    return waits


def _stub(monkeypatch, name: str, calls: list[dict], refuse: bool = False) -> None:
    class Stub(Source):
        needs_browser = True

        def fetch(self, ctx: SourceContext) -> Iterable[RawJob]:
            calls.append({"careful": pacing.active(), "cap": ctx.settings.max_detail_fetches_per_run,
                          "known": set(ctx.known_urls)})
            if refuse:
                pacing.note_refused("HTTP 403")
                return
            yield RawJob(source=name, title="Backend Engineer", company_name="Acme", url=f"https://x.test/{name}/1",
                         description=_BODY)

    Stub.name, Stub.label, Stub.description, Stub.kind = name, name, name, "browser"
    monkeypatch.setitem(_REGISTRY, name, Stub)


def _sign_in(name: str) -> None:
    with session_scope() as db:
        pacing.mark_signed_in(db, name)


def _crawl(name: str, manual: bool = False) -> Run:
    with session_scope() as db:
        return run_source(name, db, manual=manual)


def test_a_signed_in_site_gets_gaps_and_a_refusal_ends_its_visits(site, no_waiting):
    pacing.begin(lambda m: None)
    try:
        with launch_context(headless=True) as ctx:
            page = new_page(ctx)
            page.goto(f"{site.url}/list")
            assert no_waiting == []                              # nothing to wait for before the first page
            page.goto(f"{site.url}/job/1")
            assert len(no_waiting) == 1 and pacing.GAP_S[0] <= no_waiting[0] <= pacing.BREAK_S[1]
            with pytest.raises(pacing.SiteRefused):
                page.goto(f"{site.url}/forbidden")
            seen = len(site.hits)
            with pytest.raises(pacing.SiteRefused):
                page.goto(f"{site.url}/job/2")
            assert len(site.hits) == seen                        # the site is not touched again
    finally:
        pacing.end()


def test_stop_ends_a_pause_right_away():
    stop = threading.Event()
    stop.set()
    cancel.bind(stop)
    try:
        started = time.monotonic()
        pacing._wait(30)
        assert time.monotonic() - started < 1
        visits = pacing.begin(lambda m: None)
        visits.count = 1
        with pytest.raises(RuntimeError, match="stopped by user"):
            pacing._take_turn(visits, page=None)                 # no further page is opened
    finally:
        cancel.bind(None)
        pacing.end()


def test_other_sites_and_form_filling_are_not_paced(site, no_waiting):
    assert not pacing.active()
    with launch_context(headless=True) as ctx:
        page = new_page(ctx)
        page.goto(f"{site.url}/list")
        page.goto(f"{site.url}/forbidden")                       # a normal page.goto, nothing raised
    assert no_waiting == []


def test_only_signed_in_sites_slow_down(monkeypatch, no_waiting):
    calls: list[dict] = []
    _stub(monkeypatch, "stub_visitor", calls)
    _stub(monkeypatch, "stub_account", calls)
    _sign_in("stub_account")
    _crawl("stub_visitor")
    assert calls[-1] == {"careful": False, "cap": get_settings().max_detail_fetches_per_run, "known": set()}
    assert no_waiting == []                                      # no random start either
    _crawl("stub_account")
    assert calls[-1]["careful"] and calls[-1]["cap"] == pacing.DETAIL_PAGES
    assert len(no_waiting) == 1 and pacing.START_S[0] <= no_waiting[0] <= pacing.START_S[1]
    assert not pacing.active()                                   # switched off again after the run


def test_a_signed_in_site_is_read_once_a_day_unless_asked_by_name(monkeypatch, no_waiting):
    calls: list[dict] = []
    _stub(monkeypatch, "stub_daily", calls)
    _sign_in("stub_daily")
    _crawl("stub_daily")
    assert len(calls) == 1
    run = _crawl("stub_daily")
    assert len(calls) == 1 and "already read" in run.log and run.status == "ok"
    _crawl("stub_daily", manual=True)
    assert len(calls) == 2 and "https://x.test/stub_daily/1" in calls[-1]["known"]    # no need to open it again


def test_a_refused_site_rests_and_health_says_so(monkeypatch, no_waiting):
    calls: list[dict] = []
    _stub(monkeypatch, "stub_refused", calls, refuse=True)
    _sign_in("stub_refused")
    first = _crawl("stub_refused")
    assert first.status == "partial" and first.stats["blocked"]
    run = _crawl("stub_refused")
    assert len(calls) == 1 and "resting until" in run.log
    with session_scope() as db:
        health = source_health(db, ["stub_refused"])["stub_refused"]
    assert health["health"] == "blocked" and "resting until" in health["note"].lower()
    _crawl("stub_refused", manual=True)                          # the user can always try it
    assert len(calls) == 2


def test_the_rest_doubles_while_a_site_keeps_refusing():
    def add(db, name, hours_ago, stats=None, log=""):
        t = utcnow() - timedelta(hours=hours_ago)
        db.add(Run(kind="crawl", source=name, status="partial", started_at=t, finished_at=t, stats=stats or {}, log=log))
        db.commit()

    with session_scope() as db:
        add(db, "one_strike", 25, {"blocked": 1})
        assert pacing.skip_reason(db, "one_strike") is None      # one day's rest is over
        add(db, "two_strikes", 60, {"blocked": 1})
        add(db, "two_strikes", 26, log="10:00:00 skipped: resting until 01 Jan 10:00 because the site refused")
        add(db, "two_strikes", 25, log="10:00:00 HTTP 429 for https://x.test")
        assert "resting" in pacing.skip_reason(db, "two_strikes")   # two refusals in a row: two days
        add(db, "recovered", 60, {"blocked": 1})
        add(db, "recovered", 50, {"fetched": 3})
        assert pacing.skip_reason(db, "recovered") is None       # a good read clears the strikes


def test_browser_sites_keep_the_job_page_text_and_skip_pages_already_read(site):
    from jobagent.sources.generic_sites import GenericSite

    class Site(GenericSite):
        name, label, description = "site_stub", "Stub site", "stub"
        site = {"key": "stub", "search_url": "", "card_selector": "li.job", "link_selector": "a", "title_selector": "a",
                "company_selector": ".co", "location_selector": ".loc", "pages": 1}

    Site.site = {**Site.site, "search_url": f"{site.url}/list?q={{role_plus}}"}
    ctx = SourceContext(settings=get_settings(), search=SearchProfile(roles=["Engineer"]), db=None, log=lambda m: None,
                        known_urls={f"{site.url}/job/1"})
    jobs = list(Site().fetch(ctx))
    by_url = {j.url: j for j in jobs}
    assert _BODY[:40] in by_url[f"{site.url}/job/2"].description     # used to be read, then thrown away
    assert by_url[f"{site.url}/job/1"].description is None
    assert "/job/1" not in site.hits and "/job/2" in site.hits


def test_a_page_already_open_is_not_loaded_twice_for_the_ai(site, monkeypatch):
    from jobagent.sources import _extract

    monkeypatch.setattr(_extract, "run_llm", lambda *a, **k: {"jobs": [], "page_kind": "listing"})
    ctx = SourceContext(settings=get_settings(), search=SearchProfile(), db=None, log=lambda m: None)
    with launch_context(headless=True) as bctx:
        page = new_page(bctx)
        page.goto(f"{site.url}/list")
        _extract.extract_listings(ctx, page, f"{site.url}/list")
    assert [h for h in site.hits if h == "/list"] == ["/list"]


def test_the_sign_in_button_marks_the_site_and_it_can_be_undone(client, monkeypatch):
    import jobagent.api.pipeline as api

    opened: list[list[str]] = []
    monkeypatch.setattr(api.subprocess, "Popen", lambda cmd, **k: opened.append(cmd))
    assert client.post("/api/pipeline/browser-login?site=site_wellfound").status_code == 200
    assert opened

    def row() -> dict:
        return next(s for s in client.get("/api/settings/sources").json() if s["name"] == "site_wellfound")

    assert row()["signed_in"] is True
    assert client.delete("/api/pipeline/browser-login?site=site_wellfound").status_code == 200
    assert row()["signed_in"] is False
