"""Any OpenAI-compatible chat completions API: OpenAI, Google Gemini, OpenRouter, Groq, DeepSeek, Mistral, Together,
LM Studio, vLLM… Pick the server's address and a model in Settings; the key comes from JOBAGENT_OPENAI_API_KEY.

Structured replies use `response_format: json_schema` (strict). Servers that don't support it get `json_object`, and
servers that support neither are asked for JSON in words; the reply is parsed either way. No tools are offered.
"""

from __future__ import annotations

from typing import Any

import httpx

from ..config import get_settings
from .client import LLMBudgetExceeded, LLMError, LLMTimeout, LLMUnavailable
from .providers import parse_json, schema_hint

_LOCAL = ("localhost", "127.0.0.1", "0.0.0.0", "[::1]")


def _setup(choice: Any) -> tuple[str, str, str]:
    base = (getattr(choice, "base_url", "") or "https://api.openai.com/v1").rstrip("/")
    return base, getattr(choice, "model", ""), get_settings().openai_api_key.strip()


def _is_local(base: str) -> bool:
    return any(h in base for h in _LOCAL)


def check(choice: Any = None) -> dict[str, Any]:
    base, model, key = _setup(choice)
    if not model:
        return {"ok": False, "base_url": base, "error": "Pick a model for this server in Settings → AI."}
    if not key and not _is_local(base):
        return {"ok": False, "base_url": base, "model": model,
                "error": "No API key: add JOBAGENT_OPENAI_API_KEY to .env and restart JobPilot."}
    return {"ok": True, "base_url": base, "model": model, "key": "set" if key else "not needed (local server)"}


def _error(r: httpx.Response) -> LLMError:
    try:
        msg = str((r.json().get("error") or {}).get("message") or r.text)
    except Exception:
        msg = r.text
    msg = msg[:400]
    if r.status_code == 429:
        return LLMBudgetExceeded(f"The AI API reported a rate or usage limit: {msg}")
    if r.status_code in (401, 403):
        return LLMUnavailable(f"The AI API refused the key (HTTP {r.status_code}): {msg}")
    if r.status_code == 404:
        return LLMUnavailable(f"The AI API doesn't know that model or address (HTTP 404): {msg}")
    return LLMError(f"AI API HTTP {r.status_code}: {msg}")


def _format_unsupported(r: httpx.Response) -> bool:
    low = r.text.lower()
    return r.status_code in (400, 422) and any(k in low for k in ("response_format", "json_schema", "json_object",
                                                                   "structured", "not support"))


def complete(prompt: str, schema: dict[str, Any] | None, timeout_s: int, choice: Any = None) -> tuple[str, Any]:
    base, model, key = _setup(choice)
    problem = check(choice)
    if not problem["ok"]:
        raise LLMUnavailable(problem["error"])
    return call(prompt, schema, timeout_s, base=base, model=model, key=key, tag="openai")


def call(prompt: str, schema: dict[str, Any] | None, timeout_s: int, *, base: str, model: str, key: str,
         tag: str) -> tuple[str, Any]:
    """One chat completion on an OpenAI-compatible server (shared with the Gemini provider)."""
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    formats: list[dict[str, Any] | None] = [None]
    if schema is not None:
        formats = [{"type": "json_schema", "json_schema": {"name": "result", "strict": True, "schema": schema}},
                   {"type": "json_object"}, None]
    for i, fmt in enumerate(formats):
        enforced = schema is None or (fmt is not None and fmt["type"] == "json_schema")
        text = prompt if enforced else prompt + schema_hint(schema)      # json_object / plain: describe the schema
        body: dict[str, Any] = {"model": model, "messages": [{"role": "user", "content": text}]}
        if fmt is not None:
            body["response_format"] = fmt
        try:
            r = httpx.post(f"{base}/chat/completions", json=body, headers=headers, timeout=timeout_s)
        except httpx.TimeoutException as e:
            raise LLMTimeout(f"The AI API timed out after {timeout_s}s") from e
        except httpx.HTTPError as e:
            raise LLMUnavailable(f"Can't reach {base}: {e}") from e
        if r.status_code >= 400:
            if i < len(formats) - 1 and _format_unsupported(r):
                continue                   # this server can't do that reply format: try a simpler one
            raise _error(r)
        try:
            reply = r.json()["choices"][0]["message"]
        except (ValueError, KeyError, IndexError, TypeError) as e:
            raise LLMError(f"Unexpected reply from the AI API: {r.text[:300]}") from e
        if reply.get("refusal"):
            raise LLMError(f"The model declined: {str(reply['refusal'])[:300]}")
        content = (reply.get("content") or "").strip()
        label = f"{tag}:{r.json().get('model') or model}"
        return (label, content) if schema is None else (label, parse_json(content, "The AI API"))
    raise LLMError("The AI API rejected every reply format")   # pragma: no cover (the loop always returns or raises)


def list_models(base: str, key: str) -> list[str]:
    """The model ids the server offers (GET /models), for the Settings picker. [] when it can't say."""
    try:
        r = httpx.get(f"{base}/models", headers={"Authorization": f"Bearer {key}"} if key else {}, timeout=15)
        data = r.json().get("data") if r.status_code < 400 else None
    except (httpx.HTTPError, ValueError):
        return []
    ids = [str(m.get("id", "")).removeprefix("models/") for m in data or [] if isinstance(m, dict)]
    return sorted({i for i in ids if i})


def models(choice: Any = None) -> list[str]:
    base, _, key = _setup(choice)
    return list_models(base, key) if key or _is_local(base) else []
