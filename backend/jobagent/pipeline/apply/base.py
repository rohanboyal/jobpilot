"""Generic application-form handling: inspect fields (in whichever frame holds the form), execute an AI-made
fill plan, find the submit button, read the outcome."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from playwright.sync_api import Frame, Page
from rapidfuzz import fuzz, process
from rapidfuzz.utils import default_process

INSPECT_JS = r"""
() => {
  const vis = el => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const clean = t => (t || '').replace(/\s+/g, ' ').trim().slice(0, 220);
  const CTL = 'input:not([type=radio]):not([type=checkbox]):not([type=hidden]), textarea, select, [role=combobox]';
  const LABELISH = 'legend, label:not(:has(input)), [class*="label" i], [class*="question" i]';
  const labelFor = el => {
    let t = '';
    if (el.id) { try { const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`); if (l) t = l.innerText; } catch (e) {} }
    const lb = el.getAttribute('aria-labelledby');
    if (!t && lb) t = lb.split(' ').map(id => (document.getElementById(id) || {}).innerText || '').join(' ');
    if (!t && el.getAttribute('aria-label')) t = el.getAttribute('aria-label');
    if (!t) { const l = el.closest('label'); if (l) t = l.innerText; }
    if (!t) {   // walk up until a wrapper with a label-like element, but never past a container of several fields
      let n = el.parentElement;
      for (let k = 0; k < 6 && n && n.tagName !== 'FORM' && n.tagName !== 'BODY'; k++, n = n.parentElement) {
        if (n.querySelectorAll(CTL).length > 1) break;
        const lab = n.querySelector(LABELISH);
        if (lab && clean(lab.innerText)) { t = lab.innerText; break; }
      }
    }
    if (!t) {   // text block right before the control, e.g. <div>Phone</div><input>
      let p = el.previousElementSibling, k = 0;
      while (p && k < 3 && !clean(p.innerText)) { p = p.previousElementSibling; k++; }
      if (p && clean(p.innerText) && !p.querySelector(CTL) && clean(p.innerText).length < 160) t = p.innerText;
    }
    if (!t) t = el.placeholder || el.name || '';
    return clean(t);
  };
  const groupLabel = (el, name, fallback) => {
    let n = el.parentElement, k = 0;
    while (n && k < 8 && n.tagName !== 'FORM' && n.tagName !== 'BODY') {
      let holdsGroup = true;
      if (name) { try { holdsGroup = n.querySelectorAll(`input[name="${CSS.escape(name)}"]`).length > 1; } catch (e) {} }
      if (holdsGroup) {
        const lab = n.querySelector(LABELISH);
        if (lab && clean(lab.innerText)) return clean(lab.innerText);
        if (name) return fallback;
      }
      n = n.parentElement; k++;
    }
    return fallback;
  };
  const optionText = (el, label) => {
    let own = el.closest('label');
    if (!own && el.id) { try { own = document.querySelector(`label[for="${CSS.escape(el.id)}"]`); } catch (e) {} }
    let ot = own ? own.innerText : (el.getAttribute('aria-label') || '');
    if (!clean(ot)) { const sib = el.nextElementSibling || el.nextSibling; if (sib && sib.textContent) ot = sib.textContent; }
    if (!clean(ot)) ot = (el.value && el.value !== 'on') ? el.value : label;
    return clean(ot);
  };
  const out = []; let i = 0; const radios = {}; const checks = {};
  const els = Array.from(document.querySelectorAll('input, textarea, select, [role=combobox], [contenteditable=true]'));
  for (const el of els) {
    let type = (el.getAttribute('type') || '').toLowerCase();
    if (!type) type = el.tagName === 'TEXTAREA' ? 'textarea' : el.tagName === 'SELECT' ? 'select'
      : el.getAttribute('role') === 'combobox' ? 'combobox' : el.getAttribute('contenteditable') ? 'richtext' : 'text';
    if (el.getAttribute('role') === 'combobox' && el.tagName === 'INPUT') type = 'combobox';
    if (['hidden', 'submit', 'button', 'image', 'reset', 'search'].includes(type)) continue;
    if (type !== 'file' && !vis(el)) continue;
    if (el.closest('[data-ja-skip]')) continue;
    const id = 'ja' + (i++);
    el.setAttribute('data-ja-id', id);
    const label = labelFor(el);
    const required = !!(el.required || el.getAttribute('aria-required') === 'true' || /\*/.test(label));
    if (type === 'radio' || type === 'checkbox') {
      const optLabel = optionText(el, label);
      const name = el.name || '';
      if (type === 'radio') {
        const rk = name || label;
        if (!radios[rk]) {
          radios[rk] = { field_id: id, type: 'radio', label: groupLabel(el, name, label || rk), required, options: [], option_ids: [] };
          out.push(radios[rk]);
        }
        radios[rk].options.push(optLabel); radios[rk].option_ids.push(id); radios[rk].required = radios[rk].required || required;
        continue;
      }
      if (name) {
        if (!checks[name]) {
          checks[name] = { field_id: id, type: 'checkbox', label: optLabel, group_label: groupLabel(el, name, name), required, options: [], option_ids: [] };
          out.push(checks[name]);
        }
        const g = checks[name]; g.options.push(optLabel); g.option_ids.push(id); g.required = g.required || required;
        continue;
      }
      out.push({ field_id: id, type: 'checkbox', label: optLabel, required, options: [] });
      continue;
    }
    let options = [];
    if (type === 'select') options = Array.from(el.options).map(o => o.text.trim()).filter(Boolean).slice(0, 300);
    out.push({ field_id: id, type, label: label || clean(el.name), required, options,
               name: el.name || '', placeholder: el.placeholder || '', current: (el.value || '').slice(0, 80) });
  }
  for (const g of Object.values(checks)) {   // several boxes sharing a name = one "tick all that apply" question
    if (g.options.length > 1) { g.type = 'checkbox_group'; g.label = g.group_label; g.required = g.required || /\*/.test(g.group_label); }
    else { g.options = []; delete g.option_ids; }
    delete g.group_label;
  }
  return out;
}
"""

SUBMIT_SELECTORS = [
    "button[type=submit]:visible", "input[type=submit]:visible",
    "button:has-text('Submit application')", "button:has-text('Submit Application')",
    "button:has-text('Submit')", "button:has-text('Send application')", "button:has-text('Apply')",
]
REVEAL_SELECTORS = [
    "a:has-text('Apply for this job')", "button:has-text('Apply for this job')", "a:has-text('Apply now')",
    "button:has-text('Apply now')", "a:has-text('Apply Now')", "button:has-text('Apply Now')",
    "button:has-text('Apply')", "a#apply_button", "a:has-text('Apply')",
]
CONFIRMATION_MARKERS = (
    "thank you for applying", "application submitted", "application has been submitted", "we have received your",
    "we've received your", "thanks for applying", "your application was sent", "successfully submitted",
    "application received", "thank you for your application", "you have applied", "application sent",
)
ERROR_MARKERS = ("is required", "required field", "please fill", "please complete", "invalid", "must be")

Scope = Frame   # the frame that holds the form (the main frame, or an embedded ATS iframe)


@dataclass
class FillResult:
    filled: list[dict[str, Any]] = field(default_factory=list)
    failed: list[dict[str, Any]] = field(default_factory=list)
    skipped_required: list[str] = field(default_factory=list)
    uploaded_resume: bool = False


def _weight(fields: list[dict[str, Any]]) -> int:
    return len([f for f in fields if f.get("type") != "checkbox"])


def inspect_form(page: Page) -> tuple[Scope, list[dict[str, Any]]]:
    """Scan every frame and return (frame, fields) for the frame that holds the richest form."""
    best_frame, best = page.main_frame, []
    for fr in page.frames:
        try:
            fields = fr.evaluate(INSPECT_JS)
        except Exception:
            continue
        if _weight(fields) > _weight(best):
            best_frame, best = fr, fields
    return best_frame, best


def reveal_form(page: Page) -> bool:
    """Click an 'Apply' control when the form is not on the page yet."""
    for sel in REVEAL_SELECTORS:
        try:
            el = page.locator(sel).first
            if el.count() and el.is_visible(timeout=800):
                el.click(timeout=3000)
                page.wait_for_timeout(2000)
                return True
        except Exception:
            continue
    return False


_SYNONYMS = {"y": "yes", "true": "yes", "n": "no", "false": "no"}


def _best_option(value: str, options: list[str]) -> str | None:
    """Pick the option that means `value`: exact, then case-insensitive, then yes/no synonyms, then fuzzy."""
    if not options:
        return None
    if value in options:
        return value
    low = {o.strip().lower(): o for o in options}
    v = value.strip().lower()
    if v in low:
        return low[v]
    if _SYNONYMS.get(v) in low:
        return low[_SYNONYMS[v]]
    for key, o in low.items():            # "Yes, I am authorized" matches "yes"
        if key.startswith(v + ",") or key.startswith(v + " "):
            return o
    match = process.extractOne(v, list(low.keys()), scorer=fuzz.WRatio, processor=default_process)
    if match and match[1] >= 70:
        return low[match[0]]
    return None


def execute_plan(scope: Scope, fields: list[dict[str, Any]], plan: list[dict[str, Any]], resume_path: str | None,
                 pause_ms: int = 400) -> FillResult:
    by_id = {f["field_id"]: f for f in fields}
    res = FillResult()
    for item in plan:
        f = by_id.get(item.get("field_id"))
        if not f:
            continue
        action = item.get("action")
        value = (item.get("value") or "").strip()
        if action == "skip" or (not value and action not in ("upload_resume", "check")):
            if f.get("required"):
                res.skipped_required.append(f.get("label") or f["field_id"])
            continue
        loc = scope.locator(f'[data-ja-id="{f["field_id"]}"]')
        try:
            if action == "upload_resume":
                if not resume_path:
                    res.skipped_required.append("Resume file (no resume uploaded in Profile)")
                    continue
                loc.set_input_files(resume_path)
                res.uploaded_resume = True
            elif f["type"] == "checkbox_group":
                _tick_group(scope, f, value)
            elif action == "check" and f["type"] == "checkbox":
                truthy = value.lower() in ("yes", "true", "1", "checked", "on") or value == ""
                (loc.check if truthy else loc.uncheck)(force=True, timeout=4000)
            elif f["type"] in ("select", "radio", "combobox"):
                _do_select(scope, loc, f, value)
            else:
                loc.click(timeout=4000)
                loc.fill(value, timeout=6000)
            res.filled.append({"field": f.get("label"), "value": value if action != "upload_resume" else "(resume)"})
            scope.wait_for_timeout(pause_ms)
        except Exception as e:
            res.failed.append({"field": f.get("label"), "value": value, "error": str(e)[:200]})
            if f.get("required"):
                res.skipped_required.append(f.get("label") or f["field_id"])
    planned = {item.get("field_id") for item in plan}
    for f in fields:                          # a required field the plan left out entirely is just as unanswered
        if f.get("required") and f["field_id"] not in planned:
            res.skipped_required.append(f.get("label") or f["field_id"])
    return res


def _tick_group(scope: Scope, f: dict[str, Any], value: str) -> None:
    options = f.get("options") or []
    wanted = [v.strip() for v in re.split(r"[;,|]", value) if v.strip()]
    chosen = [c for c in (_best_option(v, options) for v in wanted) if c]
    if not chosen:
        raise ValueError(f"no checkbox option matches {value!r}")
    for c in dict.fromkeys(chosen):
        scope.locator(f'[data-ja-id="{f["option_ids"][options.index(c)]}"]').check(force=True, timeout=3000)


def _do_select(scope: Scope, loc, f: dict[str, Any], value: str) -> None:
    t = f["type"]
    if t == "select":
        choice = _best_option(value, f.get("options") or []) or value
        try:
            loc.select_option(label=choice, timeout=4000)
        except Exception:
            loc.select_option(value, timeout=4000)
        return
    if t == "radio":
        options = f.get("options") or []
        choice = _best_option(value, options)
        if choice is None:
            raise ValueError(f"no radio option matches {value!r}")
        rid = f["option_ids"][options.index(choice)]
        radio = scope.locator(f'[data-ja-id="{rid}"]')
        try:
            radio.check(force=True, timeout=3000)
        except Exception:
            radio.locator("xpath=ancestor::label[1]").click(timeout=3000)
        return
    # combobox / autocomplete input (react-select, Google Places and friends)
    loc.click(timeout=4000)
    try:
        loc.fill("", timeout=2000)
    except Exception:
        pass
    scope.page.keyboard.type(value, delay=20)
    scope.wait_for_timeout(700)
    opt = scope.locator(":is([role=option], [class*='option' i], .pac-item) >> visible=true").first
    try:
        if opt.count() and opt.is_visible(timeout=1500):
            opt.click(timeout=2000)
            return
    except Exception:
        pass
    # No suggestion matched. Never press Enter here: inside a <form> that submits the application.
    try:
        loc.blur(timeout=1000)
    except Exception:
        pass
    raise ValueError(f"no suggestion matched {value!r}; typed text left in the field")


def find_submit(scope: Scope):
    for sel in SUBMIT_SELECTORS:
        try:
            el = scope.locator(sel).first
            if el.count() and el.is_visible(timeout=600) and el.is_enabled():
                return el
        except Exception:
            continue
    return None


def page_outcome(scope: Scope) -> tuple[str, str]:
    """('submitted'|'error'|'unknown', snippet)"""
    try:
        text = scope.locator("body").inner_text(timeout=8000).lower()
    except Exception:
        return "unknown", ""
    for m in CONFIRMATION_MARKERS:
        if m in text:
            i = text.find(m)
            return "submitted", text[max(0, i - 80): i + 160].replace("\n", " ")
    try:
        invalid = scope.locator("[aria-invalid=true], .field_error, .error-message, [class*='error' i]:visible").count()
    except Exception:
        invalid = 0
    if invalid:
        return "error", f"{invalid} field(s) flagged invalid"
    for m in ERROR_MARKERS:
        if m in text[:20000]:
            return "error", m
    return "unknown", ""
