"""Exercises the generic form inspector/filler against a local HTML form in headless Chromium."""

from pathlib import Path

import pytest

from jobagent.pipeline.apply.base import execute_plan, find_submit, inspect_form, page_outcome

FORM = """
<!doctype html><html><body>
<h1>Apply for Backend Engineer</h1>
<form id="f">
  <label for="fn">First Name *</label><input id="fn" name="first_name" required>
  <label for="ln">Last Name *</label><input id="ln" name="last_name" required>
  <label for="em">Email *</label><input id="em" type="email" name="email" required>
  <label for="ph">Phone</label><input id="ph" type="tel" name="phone">
  <label for="cv">Resume/CV *</label><input id="cv" type="file" name="resume" style="display:none">
  <label for="cl">Cover Letter</label><textarea id="cl" name="cover_letter"></textarea>
  <label for="np">Notice period</label>
  <select id="np" name="notice"><option value="">Select...</option><option>Immediate</option><option>30 days</option><option>60 days</option></select>
  <fieldset><legend>Are you legally authorized to work in India? *</legend>
    <label><input type="radio" name="auth" value="y"> Yes</label>
    <label><input type="radio" name="auth" value="n"> No</label>
  </fieldset>
  <label><input type="checkbox" name="consent"> I agree to the privacy policy</label>
  <div class="field"><div class="label">Languages you speak *</div>
    <label><input type="checkbox" name="langs" value="en"> English</label>
    <label><input type="checkbox" name="langs" value="hi"> Hindi</label>
    <label><input type="checkbox" name="langs" value="fr"> French</label></div>
  <div class="field"><div class="label">Gender *</div>
    <input type="radio" name="gender" value="m"><span>Male</span>
    <input type="radio" name="gender" value="f"><span>Female</span></div>
  <div class="q"><div class="label">LinkedIn profile</div><div><input name="linkedin" placeholder="Start typing..."></div></div>
  <label for="sal">Expected salary</label><input id="sal" name="salary">
  <button type="submit">Submit application</button>
</form>
<script>
document.getElementById('f').addEventListener('submit', e => { e.preventDefault();
  document.body.innerHTML = '<h2>Thank you for applying!</h2><p>We have received your application.</p>'; });
</script>
</body></html>
"""


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:   # one sync Playwright per module; nesting a second one in the same thread fails
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


@pytest.fixture(scope="module")
def page(browser, tmp_path_factory):
    html = tmp_path_factory.mktemp("form") / "form.html"
    html.write_text(FORM)
    pg = browser.new_page()
    pg.goto(html.as_uri())
    return pg


def test_inspect_fill_submit(page, tmp_path: Path):
    scope, fields = inspect_form(page)
    assert scope == page.main_frame
    by_label = {f["label"]: f for f in fields}
    assert "First Name *" in by_label and by_label["First Name *"]["required"] is True
    assert by_label["Resume/CV *"]["type"] == "file"
    radio = next(f for f in fields if f["type"] == "radio")
    assert radio["options"] == ["Yes", "No"] and "authorized" in radio["label"].lower()
    sel = by_label["Notice period"]
    assert "30 days" in sel["options"]
    checkbox = next(f for f in fields if f["type"] == "checkbox")
    langs = next(f for f in fields if f["type"] == "checkbox_group")
    assert langs["options"] == ["English", "Hindi", "French"] and langs["label"].startswith("Languages")
    assert langs["required"] is True   # from the asterisk on the group label
    gender = next(f for f in fields if f["type"] == "radio" and f["label"].startswith("Gender"))
    assert gender["options"] == ["Male", "Female"]
    assert "LinkedIn profile" in by_label, [f["label"] for f in fields]   # component-wrapped input gets its real label

    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4 fake")
    plan = [
        {"field_id": by_label["First Name *"]["field_id"], "action": "fill", "value": "Sample", "confidence": 99},
        {"field_id": by_label["Last Name *"]["field_id"], "action": "fill", "value": "Person", "confidence": 99},
        {"field_id": by_label["Email *"]["field_id"], "action": "fill", "value": "r@example.com", "confidence": 99},
        {"field_id": by_label["Resume/CV *"]["field_id"], "action": "upload_resume", "value": "", "confidence": 99},
        {"field_id": by_label["Cover Letter"]["field_id"], "action": "fill", "value": "Dear team, ...", "confidence": 90},
        {"field_id": sel["field_id"], "action": "select", "value": "30 Days", "confidence": 80},
        {"field_id": radio["field_id"], "action": "select", "value": "yes", "confidence": 95},
        {"field_id": checkbox["field_id"], "action": "check", "value": "yes", "confidence": 90},
        {"field_id": langs["field_id"], "action": "select", "value": "English, Hindi", "confidence": 90},
        {"field_id": gender["field_id"], "action": "skip", "value": "", "confidence": 0},
        {"field_id": by_label["Expected salary"]["field_id"], "action": "skip", "value": "", "confidence": 0},
    ]
    res = execute_plan(scope, fields, plan, str(resume), pause_ms=10)
    assert not res.failed, res.failed
    assert res.uploaded_resume
    assert res.skipped_required == ["Gender *"]   # salary is optional; the skipped required radio group blocks submit
    assert page.is_checked("input[name=langs][value=en]") and page.is_checked("input[name=langs][value=hi])".replace("])", "]"))
    assert not page.is_checked("input[name=langs][value=fr]")
    assert page.input_value("#fn") == "Sample"
    assert page.input_value("#np") == "30 days"
    assert page.is_checked("input[name=auth][value=y]")
    assert page.is_checked("input[name=consent]")

    btn = find_submit(scope)
    assert btn is not None
    btn.click()
    page.wait_for_timeout(300)
    outcome, snippet = page_outcome(scope)
    assert outcome == "submitted" and "thank you" in snippet


def test_a_required_field_left_out_of_the_plan_blocks_submit(browser, tmp_path: Path):
    html = tmp_path / "form.html"
    html.write_text(FORM)
    pg = browser.new_page()
    pg.goto(html.as_uri())
    scope, fields = inspect_form(pg)
    first = next(f for f in fields if f["label"] == "First Name *")
    res = execute_plan(scope, fields, [{"field_id": first["field_id"], "action": "fill", "value": "Sample"}], None,
                       pause_ms=0)
    assert "Last Name *" in res.skipped_required and "Email *" in res.skipped_required
    pg.close()


IFRAME_HOST = """
<!doctype html><html><body><h1>Careers at Acme</h1><p>Apply below.</p>
<iframe id="gh" src="{src}" style="width:800px;height:600px"></iframe>
</body></html>
"""


def test_inspect_finds_form_inside_iframe(browser, tmp_path: Path):
    inner = tmp_path / "inner.html"
    inner.write_text(FORM)
    host = tmp_path / "host.html"
    host.write_text(IFRAME_HOST.format(src=inner.as_uri()))
    pg = browser.new_page()
    pg.goto(host.as_uri())
    pg.wait_for_timeout(300)
    scope, fields = inspect_form(pg)
    assert scope != pg.main_frame and len(fields) > 5
    assert find_submit(scope) is not None
    pg.close()
