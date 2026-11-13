#!/usr/bin/env bash
# Runs the API with auto-reload and the Vite dev server side by side.
set -euo pipefail
cd "$(dirname "$0")/.."
trap 'kill 0' EXIT
export JOBAGENT_SCHEDULER_ENABLED="${JOBAGENT_SCHEDULER_ENABLED:-true}"   # scheduled runs follow Settings → Automation
uv run uvicorn jobagent.main:app --reload --port "${JOBAGENT_PORT:-8000}" --app-dir backend &
(cd web && npm run dev) &
wait
