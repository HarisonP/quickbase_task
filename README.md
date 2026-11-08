# Python Service

A FastAPI service skeleton.

## Layout

```
backend/
  api/routes.py        HTTP routes (mounted under /api)
  app/main.py          FastAPI app
  app/lifespan.py      startup / shutdown hooks
  app/application.py   CLI entry point (uvicorn)
  core/config.py       settings from environment variables
  core/llm.py          shared chat model
tests/                 pytest tests
```

## Running

```bash
uv sync
uv run poe run_server_dev     # http://127.0.0.1:8000/api/health
```

## Development

```bash
uv run poe lint
uv run poe typecheck
uv run poe test
```
