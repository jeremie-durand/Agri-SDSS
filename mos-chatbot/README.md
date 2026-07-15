# mos-chatbot

Full-stack AI-powered geospatial assistant for MOS-GIS. Provides a conversational interface for querying data.

Built on [OpenGeo-AI-Assistant](https://github.com/jeremie-durand/OpenGeo-AI-Assistant) with MOS-specific overrides layered at Docker build time.

**Backend port**: 8005 | **Frontend port**: 3001

## Start

```bash
docker compose up -d mos-chatbot-backend mos-chatbot-frontend
```

## Configuration

| Variable | Description |
| --- | --- |
| `LLM_PROVIDER` | LLM provider (e.g. `openai`) |
| `LLM_API_KEY` | API key |
| `LLM_MODEL` | Model identifier |
| `CHATBOT_VERSION` | Upstream release tag to clone at build time |

## Test

```bash
make test-mos-chatbot
```

## Docs

→ [Architecture & override system](docs/ARCHITECTURE.md)
