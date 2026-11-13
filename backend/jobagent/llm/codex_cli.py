"""Codex CLI backend: `codex exec` in a read-only sandbox, signed in with the user's ChatGPT plan.

Each call runs ephemerally in an empty working directory with the user's own config ignored and every agent tool
(shell, browser, plugins, computer use) switched off, so text inside a job posting cannot make it act on the Mac.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from ..config import get_settings
from .client import LLMBudgetExceeded, LLMError, LLMTimeout, LLMUnavailable

# Places the Codex CLI ships when it is not on PATH (ChatGPT desktop app, Codex app).
_CANDIDATES = (
    "/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex",
    "/Applications/Codex.app/Contents/Resources/codex-cli/bin/codex",
    "~/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex",
)
_DISABLED_FEATURES = (
    "shell_tool", "unified_exec", "apps", "plugins", "remote_plugin", "browser_use", "browser_use_external",
    "in_app_browser", "computer_use", "image_generation", "view_image", "hooks", "skill_search", "tool_suggest",
    "sleep_tool", "memories",
)
_PREAMBLE = ("Answer directly from the text below. Do not run commands, read files or browse; you have everything "
             "you need.\n\n")
_ERROR_LINE = re.compile(r"ERROR:\s*(\{.*\})")


def find_binary() -> str | None:
    s = get_settings()
    if s.llm_bin:
        p = shutil.which(s.llm_bin) or (s.llm_bin if Path(s.llm_bin).expanduser().exists() else None)
        return str(Path(p).expanduser()) if p else None
    p = shutil.which("codex")
    if p:
        return p
    for c in _CANDIDATES:
        path = Path(c).expanduser()
        if path.exists():
            return str(path)
    return None


def check(choice: Any = None) -> dict[str, Any]:
    binary = find_binary()
    if not binary:
        return {"ok": False, "error": "Codex CLI not found. Install the ChatGPT desktop app or `npm i -g @openai/codex`."}
    try:
        out = subprocess.run([binary, "--version"], stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=20)
        version = (out.stdout or out.stderr).strip()
    except Exception as e:  # pragma: no cover
        return {"ok": False, "path": binary, "error": str(e)}
    auth = Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser() / "auth.json"
    signed_in = False
    try:
        signed_in = json.loads(auth.read_text()).get("auth_mode") == "chatgpt"
    except Exception:
        pass
    return {"ok": out.returncode == 0 and signed_in, "path": binary, "version": version, "signed_in": signed_in,
            "model": _model(choice) or "Codex default",
            **({} if signed_in else {"error": "Not signed in with ChatGPT. Open the ChatGPT app or run `codex login`."})}


def classify(msg: str) -> LLMError:
    low = msg.lower()
    if any(k in low for k in ("usage limit", "usage_limit", "rate limit", "rate_limit", "429", "quota",
                              "too many requests", "limit reached", "hit your limit")):
        return LLMBudgetExceeded(f"Codex reported a usage limit: {msg[:300]}")
    if any(k in low for k in ("not logged in", "log in", "login", "401", "unauthorized", "refresh token",
                              "authentication")):
        return LLMUnavailable(f"Codex is not signed in: {msg[:300]}")
    return LLMError(f"Codex failed: {msg[:500]}")


def _error_text(output: str) -> str:
    for line in reversed(output.splitlines()):
        m = _ERROR_LINE.search(line)
        if m:
            try:
                err = json.loads(m.group(1))
                return str((err.get("error") or {}).get("message") or err)
            except ValueError:
                return m.group(1)
    tail = [ln for ln in output.splitlines() if ln.strip()][-6:]
    return " | ".join(tail)


def _model(choice: Any = None) -> str:
    return (getattr(choice, "model", "") or get_settings().llm_model).strip()


def complete(prompt: str, schema: dict[str, Any] | None, timeout_s: int, choice: Any = None) -> tuple[str, Any]:
    """Run one prompt. Returns (model label, parsed JSON or text)."""
    s = get_settings()
    model = _model(choice)
    binary = find_binary()
    if not binary:
        raise LLMUnavailable("Codex CLI not found. Install the ChatGPT desktop app or `npm i -g @openai/codex`.")
    model_label = "codex:" + (model or "default")
    cwd = s.llm_cwd
    with tempfile.TemporaryDirectory(dir=s.data_dir, prefix="llm-") as tmp:
        out_file = Path(tmp) / "out.txt"
        args = [binary, "exec", "--ephemeral", "--skip-git-repo-check", "--ignore-user-config", "--ignore-rules",
                "-s", "read-only", "-C", str(cwd), "--color", "never", "-c", f"model_reasoning_effort={s.llm_effort}",
                "-o", str(out_file)]
        for feature in _DISABLED_FEATURES:
            args += ["--disable", feature]
        if model:
            args += ["-m", model]
        if schema is not None:
            schema_file = Path(tmp) / "schema.json"
            schema_file.write_text(json.dumps(schema))
            args += ["--output-schema", str(schema_file)]
        args.append(_PREAMBLE + prompt)
        try:
            proc = subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout_s,
                                  cwd=str(cwd))
        except subprocess.TimeoutExpired as e:
            raise LLMTimeout(f"Codex timed out after {timeout_s}s") from e
        output = (proc.stdout or "") + "\n" + (proc.stderr or "")
        reply = out_file.read_text().strip() if out_file.exists() else ""
        if proc.returncode != 0 or not reply:
            raise classify(_error_text(output) or f"exit code {proc.returncode}")
    if schema is None:
        return model_label, reply
    try:
        return model_label, json.loads(reply)
    except json.JSONDecodeError as e:
        raise LLMError(f"Codex returned non-JSON output: {reply[:300]!r}") from e
