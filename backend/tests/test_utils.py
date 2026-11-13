from datetime import UTC, datetime, timedelta

from jobagent.sources.ats_detect import apply_url_for, detect_ats
from jobagent.utils.dedup import canonical_url, dedup_key, fingerprint
from jobagent.utils.text import detect_remote, html_to_text, parse_date


def test_html_to_text_keeps_blocks():
    t = html_to_text("<div><h2>Role</h2><p>Line one</p><ul><li>a</li><li>b</li></ul><script>x()</script></div>")
    assert "Role" in t and "Line one" in t and "a" in t and "x()" not in t
    assert "\n" in t


def test_parse_date_variants():
    assert parse_date("2026-10-01T10:00:00Z") == datetime(2026, 10, 1, 10, 0)
    assert parse_date(1760000000000).year == 2025
    d = parse_date("3 days ago")
    assert d and (datetime.now(UTC).replace(tzinfo=None) - d) > timedelta(days=2, hours=23)
    assert parse_date("garbage") is None


def test_detect_remote():
    assert detect_remote("Backend Engineer (Remote)", "India") is True
    assert detect_remote("Backend Engineer", "Bengaluru (Hybrid)") is False
    assert detect_remote("Backend Engineer", "Pune") is None


def test_canonical_url_strips_tracking():
    assert canonical_url("https://x.com/jobs/1/?utm_source=a&gh_src=b&id=9") == "https://x.com/jobs/1?id=9"


def test_fingerprint_prefers_external_id():
    a = fingerprint(source="greenhouse", external_id="1", url="https://a", company="X", title="T", location=None)
    b = fingerprint(source="greenhouse", external_id="1", url="https://b", company="Y", title="U", location="Z")
    assert a == b
    c = fingerprint(source="lever", external_id="1", url="https://a", company="X", title="T", location=None)
    assert a != c


def test_dedup_key_is_cross_source_and_location_tolerant():
    k1 = dedup_key("Stripe", "Software Engineer, Backend", "Bengaluru, India")
    k2 = dedup_key("stripe", "Software Engineer - Backend (Remote)", "Bengaluru, Karnataka")
    assert k1 == k2
    assert k1 != dedup_key("Stripe", "Software Engineer, Frontend", "Bengaluru")
    # parentheticals that carry meaning are kept
    assert dedup_key("Acme", "Software Engineer (Backend)", "Bengaluru") != dedup_key("Acme", "Software Engineer (Frontend)", "Bengaluru")
    assert dedup_key("Acme", "Developer (Python)", "Pune") != dedup_key("Acme", "Developer (Java)", "Pune")
    assert dedup_key("Acme", "Developer (Remote)", "Pune") == dedup_key("Acme", "Developer (Hybrid)", "Pune")


def test_detect_ats():
    assert detect_ats("https://boards.greenhouse.io/stripe/jobs/123") == ("greenhouse", "stripe")
    assert detect_ats("https://job-boards.greenhouse.io/figma/jobs/1") == ("greenhouse", "figma")
    assert detect_ats("https://jobs.lever.co/palantir/abc") == ("lever", "palantir")
    assert detect_ats("https://jobs.ashbyhq.com/openai/xyz/application") == ("ashby", "openai")
    assert detect_ats("https://apply.workable.com/acme/j/ABC/") == ("workable", "acme")
    assert detect_ats("https://acme.workable.com/") == ("workable", "acme")
    assert detect_ats("https://jobs.smartrecruiters.com/Visa/123") == ("smartrecruiters", "Visa")
    assert detect_ats("https://www.linkedin.com/jobs/view/1") is None
    assert detect_ats("https://job-boards.greenhouse.io/embed/job_app?for=stripe&token=1") == ("greenhouse", "stripe")
    assert detect_ats("https://apply.workable.com/j/186545F8C1/apply") is None
    assert apply_url_for("lever", "https://jobs.lever.co/x/1") == "https://jobs.lever.co/x/1/apply"
    assert apply_url_for("ashby", "https://jobs.ashbyhq.com/x/1") == "https://jobs.ashbyhq.com/x/1/application"


def test_linkedin_unwrap_redirect():
    from jobagent.sources.linkedin import _unwrap_redirect

    assert _unwrap_redirect("https://www.linkedin.com/jobs/view/externalApply/1?url=https%3A%2F%2Fjobs.lever.co%2Fx%2F1&urlHash=a") == "https://jobs.lever.co/x/1"
    assert _unwrap_redirect("https://www.linkedin.com/redir/redirect?url=https%3A%2F%2Fboards.greenhouse.io%2Fy") == "https://boards.greenhouse.io/y"
    assert _unwrap_redirect("https://acme.com/apply") == "https://acme.com/apply"


def test_codex_error_classification():
    from jobagent.llm.client import LLMBudgetExceeded, LLMError, LLMUnavailable
    from jobagent.llm.codex_cli import classify

    assert isinstance(classify("You've hit your usage limit. Try again at 3pm"), LLMBudgetExceeded)
    assert isinstance(classify("stream error: 429 Too Many Requests"), LLMBudgetExceeded)
    assert isinstance(classify("401 Unauthorized: refresh token expired"), LLMUnavailable)
    assert type(classify("boom")) is LLMError


def test_strict_schema_and_drop_nulls():
    from jobagent.llm.client import drop_nulls, strict_schema
    from jobagent.llm.prompts import SCORE_SCHEMA

    s = strict_schema(SCORE_SCHEMA)
    assert set(s["required"]) == set(s["properties"])
    assert s["properties"]["salary_note"]["type"] == ["string", "null"]       # was optional
    assert s["properties"]["fit_score"]["type"] == "integer"                 # was required
    assert "salary_note" not in SCORE_SCHEMA["required"]                     # original untouched
    assert drop_nulls({"a": 1, "b": None, "c": [{"d": None, "e": 2}]}) == {"a": 1, "c": [{"e": 2}]}


def test_schedule_times_validation():
    import pytest

    from jobagent.scheduler import normalize_times

    assert normalize_times(["18:00", "9:05", "09:05"]) == ["09:05", "18:00"]
    with pytest.raises(ValueError):
        normalize_times(["25:00"])
    with pytest.raises(ValueError):
        normalize_times(["9am"])


def test_cancel_is_thread_local():
    import threading

    from jobagent import cancel

    assert cancel.requested() is False
    ev = threading.Event()
    cancel.bind(ev)
    assert cancel.requested() is False
    ev.set()
    assert cancel.requested() is True
    seen = []
    t = threading.Thread(target=lambda: seen.append(cancel.requested()))
    t.start()
    t.join()
    assert seen == [False]        # other threads are unaffected
    cancel.bind(None)


def test_unanswered_questions_are_deduplicated():
    from jobagent.pipeline.apply.runner import _dedupe_questions

    out = _dedupe_questions(["First Name*", "First name", "first name (required)", "Email*", "Email:", "Phone"])
    assert out == ["First Name*", "Email*", "Phone"]


def test_extract_prompt_keeps_posting_links_when_menus_come_first():
    from jobagent.llm.prompts import build_extract_prompt

    menu = [{"text": f"Category {i}", "href": f"https://site.example/k/topic-{i}-jobs?ref=topnavigation"} for i in range(400)]
    cards = [{"text": "Python Developer - Django/FastAPI 3-5 yrs Bangalore", "href": f"https://site.example/j/python-dev-{1677000 + i}"}
             for i in range(20)]
    prompt = build_extract_prompt("https://site.example/search", "Python Developer ...", menu + cards + cards[:3])
    assert prompt.count("/j/python-dev-") == 20               # all 20 postings reach the AI, once each
