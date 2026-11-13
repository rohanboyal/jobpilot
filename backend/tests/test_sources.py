"""Offline tests for the feed reader, the new board adapters' parsing helpers and the sites.yaml catalogue."""

from __future__ import annotations

import json

import soupsieve

from jobagent.config import SearchProfile
from jobagent.sources.arc import parse_next_data
from jobagent.sources.base import all_sources
from jobagent.sources.generic_sites import fill_template, load_sites
from jobagent.sources.nodesk import split_role_company
from jobagent.sources.we_work_remotely import split_company_title
from jobagent.sources.ziprecruiter_in import split_packed_title
from jobagent.utils.feeds import parse_feed
from jobagent.utils.text import fix_mojibake

PY_SEARCH = SearchProfile(roles=["Python Developer"], title_keywords=["python", "backend"])

RSS = """<?xml version="1.0"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/" xmlns:job_listing="https://example/job">
<channel><title>Jobs</title>
<item><title>Backend Engineer</title><link>https://example.com/jobs/1</link><guid isPermaLink="false">1</guid>
<pubDate>Wed, 21 Oct 2026 06:32:14 +0000</pubDate><description>Short &lt;b&gt;excerpt&lt;/b&gt;</description>
<content:encoded><![CDATA[<p>Full <i>text</i></p>]]></content:encoded>
<job_listing:company>Camunda</job_listing:company><job_listing:location>Worldwide</job_listing:location></item>
<item><title>No link item</title><guid>2</guid></item>
</channel></rss>"""

ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<entry><title type="text">Automic Admin</title><id>https://hasjob.co/potentiam.co.uk/m3t8m</id>
<link rel="alternate" href="https://hasjob.co/potentiam.co.uk/m3t8m"/><published>2026-10-19T11:55:35+00:00</published>
<location>Bangalore</location><content type="html">&lt;p&gt;&lt;strong&gt;Potentiam&lt;/strong&gt;&lt;/p&gt;</content></entry>
</feed>"""


def test_parse_rss_items():
    items = parse_feed(RSS)
    assert len(items) == 2
    first = items[0]
    assert first.title == "Backend Engineer"
    assert first.link == "https://example.com/jobs/1"
    assert first.guid == "1"
    assert first.published.startswith("Wed, 21 Oct 2026")
    assert "<b>excerpt</b>" in first.summary          # escaped HTML comes back as markup text
    assert "<p>Full <i>text</i></p>" in first.content   # CDATA content:encoded
    assert first.extra["job_listing:company"] == "Camunda"
    assert first.extra["job_listing:location"] == "Worldwide"
    assert items[1].link == ""


def test_parse_atom_entries():
    (entry,) = parse_feed(ATOM)
    assert entry.link == "https://hasjob.co/potentiam.co.uk/m3t8m"
    assert entry.guid == "https://hasjob.co/potentiam.co.uk/m3t8m"
    assert entry.published == "2026-10-19T11:55:35+00:00"
    assert entry.extra["location"] == "Bangalore"
    assert "<strong>Potentiam</strong>" in entry.content


def test_parse_feed_tolerates_garbage():
    assert parse_feed("") == []
    assert parse_feed("<html><body>not a feed</body></html>") == []


def test_ziprecruiter_packed_title():
    title, company, loc = split_packed_title(
        "Java Microservices Developer (GCP)\xa0 at WILLWARE TECHNOLOGIES PRIVATE LIMITED (Chennai, TN,Bengaluru, KA, HR, IN)")
    assert title == "Java Microservices Developer (GCP)"
    assert company == "WILLWARE TECHNOLOGIES PRIVATE LIMITED"
    assert loc == "Chennai, TN, Bengaluru, KA, HR, IN"
    assert split_packed_title("Python Developer at Foo (Pvt) Ltd (Pune, MH, IN)") == ("Python Developer", "Foo (Pvt) Ltd", "Pune, MH, IN")
    assert split_packed_title("Plain title without company") == ("Plain title without company", "", "")


def test_nodesk_and_wwr_title_splits():
    assert split_role_company("Software Engineer, AI Coding Tasks at Askable") == ("Software Engineer, AI Coding Tasks", "Askable")
    assert split_role_company("Head of Growth") == ("Head of Growth", "")
    assert split_company_title("DuckDuckGo: Senior Backend Engineer") == ("DuckDuckGo", "Senior Backend Engineer")
    assert split_company_title("Just a title") == ("", "Just a title")


def test_arc_next_data_parsing():
    payload = {"props": {"pageProps": {"arcJobs": [{"randomKey": "a1", "title": "Dev"}],
                                       "externalJobs": [{"randomKey": "e1", "title": "Python Developer"}]}}}
    html = f'<html><body><script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script></body></html>'
    arc_jobs, external = parse_next_data(html)
    assert [j["randomKey"] for j in arc_jobs] == ["a1"]
    assert [j["randomKey"] for j in external] == ["e1"]
    assert parse_next_data("<html>no payload</html>") == ([], [])


def test_fix_mojibake():
    assert fix_mojibake("Sothebyâ\u0080\u0099s") == "Sotheby’s"
    assert fix_mojibake("Sotheby's") == "Sotheby's"
    assert fix_mojibake("Bengaluru – India") == "Bengaluru – India"   # genuine UTF-8 untouched
    assert fix_mojibake(None) == ""


def test_new_adapters_are_registered():
    names = set(all_sources())
    expected = {"ziprecruiter_in", "hasjob", "geektrust", "himalayas", "working_nomads", "jobspresso", "nodesk",
                "we_work_remotely", "jobicy", "arbeitnow", "arc", "crossover", "dice", "eighty_thousand_hours", "justremote"}
    assert expected <= names
    for site in load_sites():
        assert f"site_{site['key']}" in names


def test_sites_catalogue_is_well_formed():
    sites = load_sites()
    keys = [s["key"] for s in sites]
    assert len(keys) == len(set(keys))
    for s in sites:
        assert s["label"] and s["search_url"].startswith("http")
        for field in ("card_selector", "title_selector", "company_selector", "location_selector", "link_selector"):
            if s.get(field):
                soupsieve.compile(s[field])     # every selector must at least parse
        if s.get("needs_login"):
            assert not s.get("enabled"), f"{s['key']} needs a login and must not be enabled by default"
    filled = fill_template("https://x.test/{role_slug}-jobs-in-{location_slug}?q={role_plus}&d={days}", "Python Developer", "New Delhi", 7)
    assert filled == "https://x.test/python-developer-jobs-in-new-delhi?q=Python+Developer&d=7"


WAD_MD = """> Markdown version of [/jobs](https://www.wearedevelopers.com/jobs). Agent guide: [/agents.md](x).

## Python Developer - PyCharm Expert

- **Company:** Mercor
- **Location:** Berlin, Germany (Remote available)
- **Salary:** €114,400.0 - €135,200.0
- **Contract:** Permanent contract
- **Published:** September 16, 2026
- [View job](https://www.wearedevelopers.com/jobs/ext/2933684-python-developer-pycharm-expert)
- [Apply](https://www.adzuna.de/details/5883488421)

## Backend Engineer

- **Company:** Native GmbH
- **Location:** Munich, Germany
- [View job](https://www.wearedevelopers.com/jobs/12345-backend-engineer)
"""


def test_wearedevelopers_markdown():
    from jobagent.sources.wearedevelopers import detail_text, parse_markdown

    jobs = parse_markdown(WAD_MD)
    assert [j["title"] for j in jobs] == ["Python Developer - PyCharm Expert", "Backend Engineer"]
    assert jobs[0]["company"] == "Mercor" and jobs[0]["apply"].startswith("https://www.adzuna.de/")
    assert jobs[0]["published"] == "September 16, 2026" and "apply" not in jobs[1]
    assert detail_text("> banner\n\n---\n\n# Title\n\nBody") == "# Title\n\nBody"


def test_reed_adapter_with_documented_fields(monkeypatch):
    import httpx

    from jobagent.config import get_settings
    from jobagent.sources import reed
    from jobagent.sources.base import SourceContext

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"].startswith("Basic ")
        if request.url.path.endswith("/search"):
            return httpx.Response(200, json={"totalResults": 2, "results": [
                {"jobId": 101, "employerName": "Acme Ltd", "jobTitle": "Python Developer", "locationName": "London",
                 "minimumSalary": 50000.0, "maximumSalary": 60000.0, "currency": "GBP", "date": "20/10/2026",
                 "jobDescription": "Short snippet", "jobUrl": "https://www.reed.co.uk/jobs/python-developer/101"},
                {"jobId": 102, "employerName": "Other", "jobTitle": "Account Manager", "locationName": "Leeds"}]})
        return httpx.Response(200, json={"jobId": 101, "jobDescription": "<p>Full <b>description</b></p>",
                                         "externalUrl": "https://boards.greenhouse.io/acme/jobs/1", "contractType": "permanent",
                                         "fullTime": True, "yearlyMinimumSalary": 50000.0, "yearlyMaximumSalary": 60000.0,
                                         "datePosted": "20/10/2026"})

    real = httpx.Client
    monkeypatch.setattr(reed, "make_client", lambda **kw: real(transport=httpx.MockTransport(handler), auth=kw.get("auth")))
    monkeypatch.setattr(reed, "polite_sleep", lambda *a, **k: None)
    settings = get_settings().model_copy(update={"reed_api_key": "k"})
    search = PY_SEARCH.model_copy(update={"countries": ["gb"], "locations": ["London"]})
    ctx = SourceContext(settings=settings, search=search, db=None, log=lambda m: None)  # type: ignore[arg-type]
    jobs = list(reed.Reed().fetch(ctx))
    assert [j.title for j in jobs] == ["Python Developer"]
    j = jobs[0]
    assert j.apply_url == "https://boards.greenhouse.io/acme/jobs/1" and j.company_name == "Acme Ltd"
    assert j.description == "Full description" and j.posted_at.day == 20
    assert j.salary_text == "£50,000 - £60,000 per year" and j.employment_type == "permanent, full time"
