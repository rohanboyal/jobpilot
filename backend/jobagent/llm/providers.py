"""The AI providers JobPilot can use, and which one the user picked (Settings -> AI).

Every provider module has the same two functions (and most a third):
  complete(prompt, schema, timeout_s, choice) -> (model label, parsed JSON or text)
  check(choice) -> {"ok": bool, "error"?: str, ...}   (cheap: never spends a call)
  models(choice) -> [model id, ...]                    (optional: what the Settings picker offers; free)
and raises the errors in llm/client.py (LLMBudgetExceeded for limits, LLMUnavailable for sign-in / missing key or
binary, LLMTimeout, LLMError for anything else). None of them gives the model tools: job text is untrusted.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from types import ModuleType
from typing import Any

from ..db import session_scope
from ..settings_store import get_setting


@dataclass(frozen=True)
class Provider:
    key: str
    label: str
    module: str
    kind: str          # plan (a subscription the user signs in to) | api (pay per use, needs a key) | local
    needs: str         # one line shown in Settings
    free: bool = False # local: calls don't count against the budget


PROVIDERS: dict[str, Provider] = {p.key: p for p in (
    Provider("codex", "Codex CLI (ChatGPT plan)", "codex_cli", "plan",
             "The ChatGPT desktop app or `npm i -g @openai/codex`, signed in with `codex login`."),
    Provider("claude", "Claude Code CLI (Claude plan)", "claude_cli", "plan",
             "Claude Code (`claude`) installed and signed in with your Claude subscription."),
    Provider("openai", "OpenAI-compatible API", "openai_compat", "api",
             "An API key in .env (JOBAGENT_OPENAI_API_KEY) and the server's address: OpenAI, OpenRouter, Groq, DeepSeek, "
             "Mistral, LM Studio…"),
    Provider("gemini", "Google Gemini API", "gemini_api", "api",
             "A Gemini API key in .env (JOBAGENT_GEMINI_API_KEY) from aistudio.google.com/apikey. Google AI Studio has a "
             "free tier with rate limits."),
    Provider("anthropic", "Anthropic API (Claude)", "anthropic_api", "api",
             "An Anthropic API key in .env (JOBAGENT_ANTHROPIC_API_KEY)."),
    Provider("ollama", "Ollama (on this computer)", "ollama", "local",
             "Ollama running with a model pulled, e.g. `ollama pull qwen3.5:4b`. Free and private.", free=True),
)}


@dataclass(frozen=True)
class Choice:
    provider: str
    model: str         # "" = the provider's default
    base_url: str


def choice(db: Any = None) -> Choice:
    def read(d: Any) -> Choice:
        key = str(get_setting(d, "llm.provider") or "codex")
        return Choice(key if key in PROVIDERS else "codex", str(get_setting(d, "llm.model") or "").strip(),
                      str(get_setting(d, "llm.base_url") or "").strip().rstrip("/"))

    if db is not None:
        return read(db)
    with session_scope() as d:
        return read(d)


def module(key: str) -> ModuleType:
    return importlib.import_module(f".{PROVIDERS[key].module}", __package__)


def schema_hint(schema: dict[str, Any]) -> str:
    """For providers that can't enforce a schema: ask for it in words (the reply is still parsed and checked)."""
    import json

    return ("\n\nReply with only one JSON object, no prose and no code fences, that matches this JSON schema:\n"
            + json.dumps(schema, separators=(",", ":")))


def parse_json(text: str, who: str) -> Any:
    """The JSON object in a reply, tolerating code fences or a sentence around it."""
    import json

    from .client import LLMError

    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        t = t.rsplit("```", 1)[0]
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        start, end = t.find("{"), t.rfind("}")
        if 0 <= start < end:
            try:
                return json.loads(t[start:end + 1])
            except json.JSONDecodeError:
                pass
    raise LLMError(f"{who} returned non-JSON output: {text[:300]!r}")
