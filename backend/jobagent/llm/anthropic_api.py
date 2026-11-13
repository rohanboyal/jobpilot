"""Anthropic API (Claude) through the official `anthropic` SDK. The key comes from JOBAGENT_ANTHROPIC_API_KEY (or
ANTHROPIC_API_KEY); pay per use. Structured replies use `output_config.format` (JSON schema); a schema the API won't
take is described in words instead and the reply is still parsed. No tools are offered.

Refusal fallback is on (`fallbacks: "default"`): if the model declines a request on safety grounds, the API retries
it on a fallback model inside the same call instead of failing.
"""

from __future__ import annotations

from typing import Any

import anthropic

from ..config import get_settings
from .client import LLMBudgetExceeded, LLMError, LLMTimeout, LLMUnavailable
from .providers import parse_json, schema_hint

DEFAULT_MODEL = "claude-opus-5-5"
_EFFORT = {"minimal": "low", "low": "low", "medium": "medium", "high": "high"}
_FALLBACK_BETA = "server-side-fallback-2026-07-01"


def _model(choice: Any) -> str:
    return getattr(choice, "model", "") or DEFAULT_MODEL


def check(choice: Any = None) -> dict[str, Any]:
    if not get_settings().anthropic_api_key.strip():
        return {"ok": False, "model": _model(choice),
                "error": "No API key: add JOBAGENT_ANTHROPIC_API_KEY to .env and restart JobPilot."}
    return {"ok": True, "model": _model(choice), "key": "set"}


def models(choice: Any = None) -> list[str]:
    """Claude models this key can use (free to ask)."""
    key = get_settings().anthropic_api_key.strip()
    if not key:
        return []
    try:
        return [m.id for m in anthropic.Anthropic(api_key=key, timeout=15, max_retries=1).models.list()]
    except anthropic.AnthropicError:
        return []


def _create(client: anthropic.Anthropic, model: str, text: str, schema: dict[str, Any] | None) -> Any:
    output_config: dict[str, Any] = {"effort": _EFFORT.get(get_settings().llm_effort, "low")}
    if schema is not None:
        output_config["format"] = {"type": "json_schema", "schema": schema}
    return client.beta.messages.create(
        model=model, max_tokens=16000, betas=[_FALLBACK_BETA], fallbacks="default",
        output_config=output_config, messages=[{"role": "user", "content": text}],
    )


def complete(prompt: str, schema: dict[str, Any] | None, timeout_s: int, choice: Any = None) -> tuple[str, Any]:
    problem = check(choice)
    if not problem["ok"]:
        raise LLMUnavailable(problem["error"])
    model = _model(choice)
    client = anthropic.Anthropic(api_key=get_settings().anthropic_api_key.strip(), timeout=timeout_s, max_retries=1)
    try:
        try:
            response = _create(client, model, prompt, schema)
        except anthropic.BadRequestError as e:
            if schema is None or not any(k in str(e).lower() for k in ("schema", "format", "output_config")):
                raise
            response = _create(client, model, prompt + schema_hint(schema), None)   # schema not accepted: ask in words
    except anthropic.AuthenticationError as e:
        raise LLMUnavailable(f"The Anthropic API refused the key: {e}") from e
    except anthropic.PermissionDeniedError as e:
        raise LLMUnavailable(f"The Anthropic key may not use {model}: {e}") from e
    except anthropic.NotFoundError as e:
        raise LLMUnavailable(f"The Anthropic API doesn't know the model {model}: {e}") from e
    except anthropic.RateLimitError as e:
        raise LLMBudgetExceeded(f"The Anthropic API reported a rate limit: {e}") from e
    except anthropic.APITimeoutError as e:
        raise LLMTimeout(f"The Anthropic API timed out after {timeout_s}s") from e
    except anthropic.APIConnectionError as e:
        raise LLMUnavailable(f"Can't reach the Anthropic API: {e}") from e
    except anthropic.APIStatusError as e:
        raise LLMError(f"Anthropic API error {e.status_code}: {e}") from e

    if response.stop_reason == "refusal":
        raise LLMError("Claude declined this request")
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    label = f"anthropic:{response.model or model}"
    return (label, text) if schema is None else (label, parse_json(text, "The Anthropic API"))
