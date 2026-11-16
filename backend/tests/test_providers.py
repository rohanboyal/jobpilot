"""Every AI provider: what is sent (no tools, schema enforced), how replies and errors come back, and that run_llm
uses the one picked in Settings. No real AI is called."""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from jobagent.config import get_settings
from jobagent.db import session_scope
from jobagent.llm import anthropic_api, claude_cli, gemini_api, openai_compat
from jobagent.llm import client as llm
from jobagent.llm.client import LLMBudgetExceeded, LLMError, LLMUnavailable
from jobagent.llm.providers import Choice
from jobagent.settings_store import set_setting

SCHEMA = llm.strict_schema({"type": "object", "properties": {"fit": {"type": "integer"}, "why": {"type": "string"}},
                               "required": ["fit"]})


@pytest.fixture
def pick(client):          # the API client fixture: the database exists
    """Choose a provider in Settings for one test, then go back to Codex."""
    def choose(provider: str, model: str = "", base_url: str = "https://api.openai.com/v1") -> None:
        with session_scope() as db:
            for k, v in (("llm.provider", provider), ("llm.model", model), ("llm.base_url", base_url)):
                set_setting(db, k, v)
    yield choose
    choose("codex")


@pytest.fixture
def keys(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "openai_api_key", "sk-test")
    monkeypatch.setattr(s, "anthropic_api_key", "sk-ant-test")
    monkeypatch.setattr(s, "gemini_api_key", "gm-test")
    return s


# ---------------------------------------------------------------- OpenAI-compatible

def _reply(status: int, payload: dict[str, Any]) -> httpx.Response:
    return httpx.Response(status, json=payload, request=httpx.Request("POST", "https://x.test"))


def test_openai_compatible_sends_a_strict_schema_and_falls_back_when_the_server_cannot(monkeypatch, keys):
    sent: list[dict[str, Any]] = []

    def post(url, json, headers, timeout):      # noqa: A002
        sent.append({"url": url, "body": json, "headers": headers})
        if json.get("response_format", {}).get("type") == "json_schema":
            return _reply(400, {"error": {"message": "response_format json_schema is not supported by this model"}})
        return _reply(200, {"model": "llama-3.3-70b", "choices": [{"message": {"content": '```json\n{"fit": 72}\n```'}}]})

    monkeypatch.setattr(openai_compat.httpx, "post", post)
    choice = Choice("openai", "llama-3.3-70b", "https://api.groq.com/openai/v1/")
    label, out = openai_compat.complete("Rate it", SCHEMA, 30, choice)
    assert out == {"fit": 72} and label == "openai:llama-3.3-70b"
    assert sent[0]["url"] == "https://api.groq.com/openai/v1/chat/completions"
    assert sent[0]["headers"] == {"Authorization": "Bearer sk-test"}
    assert sent[0]["body"]["response_format"]["json_schema"]["strict"] is True
    assert "tools" not in sent[0]["body"]                       # never any tools
    assert sent[1]["body"]["response_format"] == {"type": "json_object"}
    assert "JSON schema" in sent[1]["body"]["messages"][0]["content"]   # described in words instead


def test_openai_compatible_errors_and_keys(monkeypatch, keys):
    monkeypatch.setattr(openai_compat.httpx, "post", lambda *a, **k: _reply(429, {"error": {"message": "quota"}}))
    with pytest.raises(LLMBudgetExceeded):
        openai_compat.complete("x", None, 30, Choice("openai", "gpt-x", "https://api.openai.com/v1"))
    monkeypatch.setattr(openai_compat.httpx, "post", lambda *a, **k: _reply(401, {"error": {"message": "bad key"}}))
    with pytest.raises(LLMUnavailable):
        openai_compat.complete("x", None, 30, Choice("openai", "gpt-x", "https://api.openai.com/v1"))
    monkeypatch.setattr(keys, "openai_api_key", "")
    assert not openai_compat.check(Choice("openai", "gpt-x", "https://api.openai.com/v1"))["ok"]
    assert openai_compat.check(Choice("openai", "qwen", "http://localhost:1234/v1"))["ok"]     # local: no key needed
    assert "model" in openai_compat.check(Choice("openai", "", "https://api.openai.com/v1"))["error"]


# ---------------------------------------------------------------- Claude Code CLI

def test_claude_cli_runs_with_every_tool_off_and_reads_the_structured_reply(monkeypatch):
    calls: list[list[str]] = []
    inputs: list[str] = []

    def run(args, **kw):
        calls.append(args)
        inputs.append(kw.get("input"))
        out = {"is_error": False, "result": "", "structured_output": {"fit": 81},
               "modelUsage": {"claude-haiku-4-5": {}, "claude-opus-5-5": {}}}
        return subprocess.CompletedProcess(args, 0, json.dumps(out), "")

    monkeypatch.setattr(claude_cli, "find_binary", lambda: "/bin/claude")
    monkeypatch.setattr(claude_cli.subprocess, "run", run)
    label, out = claude_cli.complete("Rate it", SCHEMA, 30, Choice("claude", "", ""))
    assert out == {"fit": 81} and label == "claude:claude-opus-5-5"
    a = calls[0]
    assert a[a.index("--tools") + 1] == "" and a[a.index("--setting-sources") + 1] == ""
    assert {"-p", "--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence"} <= set(a)
    assert json.loads(a[a.index("--json-schema") + 1]) == SCHEMA
    assert inputs == ["Rate it"] and "Rate it" not in a          # the prompt goes in on stdin, never as an argument


def test_claude_cli_limits_and_sign_in(monkeypatch):
    monkeypatch.setattr(claude_cli, "find_binary", lambda: "/bin/claude")
    for status, text, err in ((429, "Claude AI usage limit reached", LLMBudgetExceeded),
                              (None, "Invalid API key · Please run /login", LLMUnavailable)):
        body = json.dumps({"is_error": True, "result": text, "api_error_status": status})
        monkeypatch.setattr(claude_cli.subprocess, "run", lambda args, b=body, **kw: subprocess.CompletedProcess(args, 1, b, ""))
        with pytest.raises(err):
            claude_cli.complete("x", None, 30, Choice("claude", "", ""))
    monkeypatch.setattr(claude_cli, "find_binary", lambda: None)
    assert not claude_cli.check()["ok"]


# ---------------------------------------------------------------- Anthropic API

class _FakeAnthropic:
    sent: list[dict[str, Any]] = []
    reply: Any = None

    def __init__(self, **kw):
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        _FakeAnthropic.sent.append(kw)
        return _FakeAnthropic.reply


def test_anthropic_api_uses_structured_output_and_refusal_fallback(monkeypatch, keys):
    _FakeAnthropic.sent = []
    _FakeAnthropic.reply = SimpleNamespace(stop_reason="end_turn", model="claude-opus-5-5",
                                           content=[SimpleNamespace(type="text", text='{"fit": 64}')])
    monkeypatch.setattr(anthropic_api.anthropic, "Anthropic", _FakeAnthropic)
    label, out = anthropic_api.complete("Rate it", SCHEMA, 30, Choice("anthropic", "", ""))
    assert out == {"fit": 64} and label == "anthropic:claude-opus-5-5"
    kw = _FakeAnthropic.sent[0]
    assert kw["model"] == anthropic_api.DEFAULT_MODEL and kw["fallbacks"] == "default"
    assert kw["output_config"]["format"] == {"type": "json_schema", "schema": SCHEMA} and "tools" not in kw
    _FakeAnthropic.reply = SimpleNamespace(stop_reason="refusal", model="m", content=[])
    with pytest.raises(LLMError):
        anthropic_api.complete("x", SCHEMA, 30, Choice("anthropic", "", ""))
    monkeypatch.setattr(keys, "anthropic_api_key", "")
    with pytest.raises(LLMUnavailable):
        anthropic_api.complete("x", SCHEMA, 30, Choice("anthropic", "", ""))


# ---------------------------------------------------------------- the choice in Settings

def test_run_llm_uses_the_provider_picked_in_settings(client, pick, monkeypatch, keys):
    seen: list[Choice] = []
    monkeypatch.setattr(openai_compat, "complete", lambda p, s, t, choice=None: seen.append(choice) or ("openai:m", {"fit": 1}))
    assert client.put("/api/settings/runtime", json={"llm.provider": "nope"}).status_code == 400
    assert client.put("/api/settings/runtime", json={"llm.base_url": "ftp://x"}).status_code == 400
    r = client.put("/api/settings/runtime", json={"llm.provider": "openai", "llm.model": "gemini-2.5-flash",
                                                  "llm.base_url": "https://generativelanguage.googleapis.com/v1beta/openai"})
    assert r.status_code == 200
    from jobagent.llm.client import run_llm

    assert run_llm("x", purpose="test", schema=SCHEMA, enforce_budget=False) == {"fit": 1}
    assert seen[0].model == "gemini-2.5-flash" and seen[0].base_url.endswith("/v1beta/openai")
    llm = client.get("/api/settings").json()["llm"]
    assert llm["provider"] == "openai" and llm["primary"]["ok"] and llm["budget"]["provider"] == "openai"
    assert {p["key"] for p in llm["providers"]} == {"codex", "claude", "openai", "gemini", "anthropic", "ollama"}
    assert "sk-test" not in json.dumps(client.get("/api/settings").json())      # keys never leave .env


def test_a_local_main_model_is_never_blocked_by_the_call_caps(pick):
    pick("ollama", "qwen3.5:4b")
    with session_scope() as db:
        assert llm.budget_status(db)["ok"] is True


# ---------------------------------------------------------------- Google Gemini

def test_gemini_uses_googles_endpoint_its_own_key_and_lists_chat_models(client, pick, monkeypatch, keys):
    sent: list[dict[str, Any]] = []

    def post(url, json, headers, timeout):      # noqa: A002
        sent.append({"url": url, "body": json, "headers": headers})
        return _reply(200, {"model": json["model"], "choices": [{"message": {"content": '{"fit": 77}'}}]})

    def get(url, headers, timeout):
        assert url == gemini_api.BASE_URL + "/models" and headers == {"Authorization": "Bearer gm-test"}
        return httpx.Response(200, json={"data": [{"id": "models/gemini-x-flash"}, {"id": "models/gemini-embedding-001"},
                                                  {"id": "models/text-embedding-004"}, {"id": "models/gemini-x-pro"}]},
                              request=httpx.Request("GET", url))

    monkeypatch.setattr(openai_compat.httpx, "post", post)
    monkeypatch.setattr(openai_compat.httpx, "get", get)
    pick("gemini")
    assert "Pick a Gemini model" in client.get("/api/settings").json()["llm"]["primary"]["error"]
    assert client.get("/api/settings/llm/models").json() == {"models": ["gemini-x-flash", "gemini-x-pro"]}
    pick("gemini", "gemini-x-flash")
    assert llm.run_llm("Rate it", purpose="test", schema=SCHEMA, enforce_budget=False) == {"fit": 77}
    assert sent[0]["url"] == gemini_api.BASE_URL + "/chat/completions"
    assert sent[0]["headers"] == {"Authorization": "Bearer gm-test"} and sent[0]["body"]["model"] == "gemini-x-flash"
    assert "gm-test" not in json.dumps(client.get("/api/settings").json())
    monkeypatch.setattr(keys, "gemini_api_key", "")
    assert "JOBAGENT_GEMINI_API_KEY" in gemini_api.check(Choice("gemini", "gemini-x-flash", ""))["error"]


# ---------------------------------------------------------------- setup check (SETUP.md relies on it)

def test_doctor_json_lists_what_is_left_without_personal_values(client, monkeypatch):
    from jobagent import cli
    from jobagent.config import AnswerBank

    bank = AnswerBank(identity={"full_name": "Test Person", "email": "test.person@example.com", "phone": ""})
    monkeypatch.setattr(cli, "load_answer_bank", lambda s=None: bank)
    checks = {c["check"]: c for c in cli.readiness()}
    answers = checks["Your answers (name, email, phone)"]
    assert answers["detail"] == "2 of 3 filled" and answers["needs_you"] and answers["fix"]
    assert all({"check", "ok", "detail", "fix", "needs_you"} <= set(c) for c in checks.values())
    assert "Test Person" not in json.dumps(list(checks.values())) and "example.com" not in json.dumps(list(checks.values()))
