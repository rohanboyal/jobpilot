"""The one way JobPilot calls a language model.

Main provider: the one picked in Settings -> AI (`llm.provider`, see llm/providers.py). The default is the Codex CLI
(`codex exec`) signed in with the user's ChatGPT plan; the Claude Code CLI, any OpenAI-compatible API, the Anthropic
API and a local Ollama model are the others. Optional fallback: a local Ollama model, used only when the main
provider reports a usage limit or is unavailable, and only for the purposes in `llm.fallback_purposes`.

Every call is logged to the llm_calls table and counted against JOBAGENT_LLM_MAX_CALLS_PER_5H / _PER_DAY, so a
run can never drain the plan. Prompts and JSON schemas live in llm/prompts.py.
"""

from __future__ import annotations

import copy
import threading
import time
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import session_scope
from ..models import LlmCall, utcnow


class LLMError(RuntimeError):
    pass


class LLMBudgetExceeded(LLMError):
    """The local call budget or the provider's own usage limit was reached."""


class LLMUnavailable(LLMError):
    """The provider is not installed, not signed in, or not running."""


class LLMTimeout(LLMError):
    """The provider took longer than the timeout to answer."""


# When the main AI stops answering, every call would otherwise wait the full timeout (4 minutes per page or job).
# After two timeouts in a row it rests for a while: calls fail at once (or use the Ollama fallback when that is on).
_REST_S, _REST_AFTER = 600, 2
_timeouts: list[float] = []
_timeouts_lock = threading.Lock()


def ai_resting() -> float:
    """Seconds left before the main AI is tried again after repeated timeouts (0 = not resting)."""
    with _timeouts_lock:
        if len(_timeouts) < _REST_AFTER:
            return 0.0
        return max(0.0, _timeouts[-1] + _REST_S - time.monotonic())


# ---------------------------------------------------------------------------
# Budget and bookkeeping
# ---------------------------------------------------------------------------


codex_resting = ai_resting          # the name used before other providers existed


def model_name(pick: Any) -> str:
    """The model the main AI uses, for display."""
    from .anthropic_api import DEFAULT_MODEL

    s = get_settings()
    return pick.model or {"codex": s.llm_model or "Codex default", "claude": "Claude Code default",
                          "anthropic": DEFAULT_MODEL, "ollama": s.ollama_model}.get(pick.provider, "not set")


def budget_status(db: Session) -> dict[str, Any]:
    from .providers import PROVIDERS, choice

    s = get_settings()
    pick = choice(db)
    free = PROVIDERS[pick.provider].free              # a local model costs nothing: the caps don't apply
    now = utcnow()
    base = select(func.count(LlmCall.id)).where(LlmCall.ok.is_(True), LlmCall.model.not_like("ollama:%"))   # local calls are free
    used_5h = db.scalar(base.where(LlmCall.created_at >= now - timedelta(hours=5))) or 0
    used_day = db.scalar(base.where(LlmCall.created_at >= now - timedelta(hours=24))) or 0
    return {
        "window_5h": {"used": used_5h, "max": s.llm_max_calls_per_5h},
        "day": {"used": used_day, "max": s.llm_max_calls_per_day},
        "provider": pick.provider,
        "provider_label": PROVIDERS[pick.provider].label,
        "model": model_name(pick),
        "effort": s.llm_effort,
        "ok": free or (used_5h < s.llm_max_calls_per_5h and used_day < s.llm_max_calls_per_day),
    }


def _record(purpose: str, model: str, ok: bool, duration_ms: int, input_chars: int, error: str | None) -> None:
    """Bookkeeping must never break the pipeline, but it should survive a briefly locked database."""
    for attempt in range(4):
        try:
            with session_scope() as db:
                db.add(LlmCall(purpose=purpose, model=model[:40], ok=ok, duration_ms=duration_ms,
                               input_chars=input_chars, error=(error or None) and error[:2000]))
            return
        except Exception:
            time.sleep(0.5 * (attempt + 1))


# ---------------------------------------------------------------------------
# Strict schemas (OpenAI structured outputs require every property to be listed as required)
# ---------------------------------------------------------------------------


def strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Make every object property required; properties that were optional become nullable instead."""

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            node = {k: walk(v) for k, v in node.items()}
            if node.get("type") == "object" and isinstance(node.get("properties"), dict):
                required = set(node.get("required") or [])
                for name, prop in node["properties"].items():
                    if name not in required and isinstance(prop, dict):
                        t = prop.get("type")
                        if isinstance(t, str):
                            prop["type"] = [t, "null"]
                        if isinstance(prop.get("enum"), list) and None not in prop["enum"]:
                            prop["enum"] = [*prop["enum"], None]
                node["required"] = list(node["properties"])
                node["additionalProperties"] = False
            return node
        if isinstance(node, list):
            return [walk(x) for x in node]
        return node

    return walk(copy.deepcopy(schema))


def drop_nulls(value: Any) -> Any:
    """Remove keys whose value is None, so optional fields behave as before (absent rather than null)."""
    if isinstance(value, dict):
        return {k: drop_nulls(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [drop_nulls(v) for v in value]
    return value


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_llm(
    prompt: str,
    *,
    purpose: str,
    schema: dict[str, Any] | None = None,
    system: str | None = None,
    timeout_s: int | None = None,
    db: Session | None = None,
    enforce_budget: bool = True,
) -> Any:
    """Return the structured object when `schema` is given, otherwise the text reply."""
    from functools import partial

    from . import ollama
    from .providers import PROVIDERS, choice, module

    s = get_settings()
    pick = choice(db)
    label = PROVIDERS[pick.provider].label
    timeout_s = timeout_s or s.llm_timeout_s
    full_prompt = (system.strip() + "\n\n" + prompt) if system else prompt
    budget_error: LLMBudgetExceeded | None = None

    if enforce_budget:
        if db is not None:
            status = budget_status(db)
        else:
            with session_scope() as _db:
                status = budget_status(_db)
        if not status["ok"]:
            budget_error = LLMBudgetExceeded(
                f"AI call budget reached ({status['window_5h']['used']}/{status['window_5h']['max']} in 5h, "
                f"{status['day']['used']}/{status['day']['max']} today). Raise JOBAGENT_LLM_MAX_CALLS_* or wait."
            )

    primary_error: LLMError | None = budget_error
    rest = ai_resting() if enforce_budget else 0.0           # the AI settings test always tries it for real
    if primary_error is None and rest:
        primary_error = LLMUnavailable(f"{label} stopped answering ({_REST_AFTER} timeouts in a row); "
                                       f"trying it again in {int(rest // 60) + 1} min")
    if primary_error is None:
        try:
            result = _call(partial(module(pick.provider).complete, choice=pick), pick.provider, purpose, full_prompt,
                           schema, timeout_s)
            with _timeouts_lock:
                _timeouts.clear()
            return result
        except LLMTimeout:
            with _timeouts_lock:
                _timeouts.append(time.monotonic())
            raise
        except (LLMBudgetExceeded, LLMUnavailable) as e:   # limits and sign-in problems may fall back; bad output does not
            primary_error = e

    if pick.provider != "ollama" and ollama.fallback_allowed(purpose, db):
        return _call(ollama.complete, "ollama", purpose, full_prompt, schema, timeout_s)
    raise primary_error


def _call(fn: Any, provider: str, purpose: str, prompt: str, schema: dict[str, Any] | None, timeout_s: int) -> Any:
    started = time.monotonic()
    model = provider
    try:
        model, result = fn(prompt, strict_schema(schema) if schema is not None else None, timeout_s)
    except LLMError as e:
        _record(purpose, model, False, int((time.monotonic() - started) * 1000), len(prompt), str(e))
        raise
    _record(purpose, model, True, int((time.monotonic() - started) * 1000), len(prompt), None)
    return drop_nulls(result) if schema is not None else result


def provider_models() -> list[str]:
    """Model ids the main AI's provider offers, for the Settings picker ([] when it can't list them)."""
    from .providers import choice, module

    pick = choice()
    fn = getattr(module(pick.provider), "models", None)
    return fn(pick) if fn else []


def provider_status() -> dict[str, Any]:
    """The main AI and its readiness (no call is spent), the Ollama fallback, and every provider to choose from."""
    from . import ollama
    from .providers import PROVIDERS, choice, module

    pick = choice()
    p = PROVIDERS[pick.provider]
    primary = module(pick.provider).check(pick)
    return {"provider": pick.provider, "label": p.label, "model": model_name(pick), "base_url": pick.base_url,
            "primary": primary, "ollama": primary if pick.provider == "ollama" else ollama.check(),
            "providers": [{"key": x.key, "label": x.label, "kind": x.kind, "needs": x.needs} for x in PROVIDERS.values()]}
