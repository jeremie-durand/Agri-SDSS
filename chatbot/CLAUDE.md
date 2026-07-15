# chatbot

This directory integrates [OpenGeo-AI-Assistant](https://github.com/jeremie-durand/OpenGeo-AI-Assistant) into the Agri-SDSS platform as a SDSS (Spatial Decision Support System) chatbot focused on Quebec agriculture.

Architecture, override layout, service wiring, SDSS tools, LLM configuration, and the upstream upgrade process are documented in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## The override rule

`chatbot` does **not** fork the upstream chatbot — Docker builds clone the upstream at the pinned tag (`CHATBOT_VERSION` in `.env`) and then copy `chatbot/overrides/` on top. Files in `overrides/` with the same relative path as an upstream file **replace** it; new files are additive.

To upgrade the upstream chatbot, bump `CHATBOT_VERSION` in `.env` and verify that the override files still apply cleanly (no signature drift).

## Testing

```bash
# Run all chatbot tests (also lints both Dockerfiles with hadolint)
make test-chatbot

# Tests only (no hadolint)
docker compose run --rm chatbot-backend pytest chatbot/test/ -v

# Single test file
docker compose run --rm chatbot-backend pytest chatbot/test/test_service_connectivity.py -v
```

Test markers follow the project convention:

| Marker | Meaning |
| --- | --- |
| `unit` | Pure logic, no external calls |
| `mocked` | HTTP calls replaced by `unittest.mock` |
| `integration` | Requires live services |

`test/conftest.py` sets the internal service env vars for test runs.

## Development guidelines

- Keep changes in `overrides/` minimal. Prefer upstream contributions for generic fixes; use overrides only for MOS-specific behaviour.
- When upgrading `CHATBOT_VERSION`, diff the upstream files touched by `overrides/` to catch interface drift early.
- The router agent in upstream (`geoint/router_agent.py`) classifies queries before routing. If adding MOS-specific prompt patterns, add a pre-check there (via an override) rather than tuning the generic LLM classifier.
- Add `@pytest.mark.unit` tests for all new helpers in `tools/`. Add `@pytest.mark.mocked` tests for any new HTTP calls to internal services.
