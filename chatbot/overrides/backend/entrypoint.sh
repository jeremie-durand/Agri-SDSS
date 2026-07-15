#!/bin/sh
set -e
# Start local Ollama when LLM_BASE_URL targets localhost:11434.
# For external providers (OpenAI, Anthropic, etc.), set LLM_BASE_URL to their
# endpoint and this block is skipped entirely.
if printf '%s' "${LLM_BASE_URL:-}" | grep -qE '(localhost|127\.0\.0\.1):11434'; then
    export HOME="/app"
    export OLLAMA_HOME="/app/.ollama"
    ollama serve &
    # Pull model in background so FastAPI starts immediately.
    # LLM calls will fail until the pull completes, but the health endpoint works.
    (
        until curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; do sleep 2; done
        [ -n "${LLM_MODEL:-}" ] && ollama pull "$LLM_MODEL" >/dev/null 2>&1 || true
    ) &
fi
exec uvicorn sdss_main:app --host 0.0.0.0 --port 8000
