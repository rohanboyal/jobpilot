"""Ollama's HTTP API (no install step in JobPilot; uses what Ollama already has).

Either the main AI (Settings -> AI -> Ollama) or the optional fallback: used when the main AI reports a usage limit
or is unavailable, and only for the purposes the user allowed (a small local model is fine for scoring and page
extraction, not for writing cover letters).
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import session_scope
from ..settings_store import get_setting
from .client import LLMError, LLMUnavailable


def fallback_allowed(purpose: str, db: Session | None) -> bool:
    def _read(d: Session) -> bool:
        return bool(get_setting(d, "llm.fallback_enabled")) and purpose in (get_setting(d, "llm.fallback_purposes") or [])

    if db is not None:
        return _read(db)
    with session_scope() as d:
        return _read(d)


def _model(db: Session | None = None) -> str:
    if db is not None:
        return str(get_setting(db, "llm.fallback_model") or get_settings().ollama_model)
    with session_scope() as d:
        return str(get_setting(d, "llm.fallback_model") or get_settings().ollama_model)


def check(choice: Any = None) -> dict[str, Any]:
    s = get_settings()
    try:
        r = httpx.get(f"{s.ollama_url}/api/tags", timeout=4)
        names = [m.get("name") for m in r.json().get("models", [])]
    except Exception:
        return {"ok": False, "running": False, "models": [], "error": "Ollama is not running"}
    model = getattr(choice, "model", "") or _model()
    return {"ok": model in names, "running": True, "models": names, "model": model,
            **({} if model in names else {"error": f"model {model} is not pulled (ollama pull {model})"})}


def models(choice: Any = None) -> list[str]:
    return list(check(choice).get("models") or [])


def complete(prompt: str, schema: dict[str, Any] | None, timeout_s: int, choice: Any = None) -> tuple[str, Any]:
    s = get_settings()
    model = getattr(choice, "model", "") or _model()      # the main AI's model, else the fallback model
    body: dict[str, Any] = {"model": model, "prompt": prompt, "stream": False, "think": False,
                            "options": {"temperature": 0.2, "num_ctx": 16384}}
    if schema is not None:
        body["format"] = schema
    try:
        r = httpx.post(f"{s.ollama_url}/api/generate", json=body, timeout=timeout_s)
    except httpx.ConnectError as e:
        raise LLMUnavailable("Ollama is not running") from e
    except httpx.TimeoutException as e:
        raise LLMError(f"Ollama timed out after {timeout_s}s") from e
    if r.status_code == 404:
        raise LLMUnavailable(f"Ollama model {model} is not pulled")
    if r.status_code >= 400:
        raise LLMError(f"Ollama HTTP {r.status_code}: {r.text[:300]}")
    text = (r.json().get("response") or "").strip()
    label = f"ollama:{model}"
    if schema is None:
        return label, text
    try:
        return label, json.loads(text)
    except json.JSONDecodeError as e:
        raise LLMError(f"Ollama returned non-JSON output: {text[:300]!r}") from e
