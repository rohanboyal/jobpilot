"""Google Gemini through its OpenAI-compatible endpoint. The key comes from JOBAGENT_GEMINI_API_KEY (or GEMINI_API_KEY);
get one at https://aistudio.google.com/apikey (Google AI Studio has a free tier with rate limits). Structured replies
use a strict JSON schema; no tools are offered.
"""

from __future__ import annotations

from typing import Any

from ..config import get_settings
from .client import LLMUnavailable
from .openai_compat import call, list_models

BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"


def _key() -> str:
    return get_settings().gemini_api_key.strip()


def check(choice: Any = None) -> dict[str, Any]:
    model = getattr(choice, "model", "")
    if not _key():
        return {"ok": False, "model": model,
                "error": "No API key: add JOBAGENT_GEMINI_API_KEY to .env (from aistudio.google.com/apikey) and restart."}
    if not model:
        return {"ok": False, "error": "Pick a Gemini model in Settings → AI (the list comes from Google)."}
    return {"ok": True, "model": model, "key": "set"}


def complete(prompt: str, schema: dict[str, Any] | None, timeout_s: int, choice: Any = None) -> tuple[str, Any]:
    problem = check(choice)
    if not problem["ok"]:
        raise LLMUnavailable(problem["error"])
    return call(prompt, schema, timeout_s, base=BASE_URL, model=problem["model"], key=_key(), tag="gemini")


def models(choice: Any = None) -> list[str]:
    """Gemini models that can chat (embedding and image models left out)."""
    if not _key():
        return []
    return [m for m in list_models(BASE_URL, _key()) if "gemini" in m and "embedding" not in m and "image" not in m]
