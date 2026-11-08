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
  core/db.py           async database engine and sessions
  core/models.py       SQLAlchemy models
migrations/            Alembic migrations
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

## Database

```bash
uv run poe db               # start Postgres (docker compose)
uv run poe migrate          # create our tables (Alembic) + the LangGraph checkpointer's tables
uv run poe import_tickets   # import data/tickets.json (existing ids are skipped)
```

## Migrations

Schema changes are managed with [Alembic](https://alembic.sqlalchemy.org): one file per change in `migrations/versions/`, using `DATABASE_URL`.

```bash
uv run alembic upgrade head                            # apply pending migrations
uv run alembic downgrade -1                            # undo the last one
uv run alembic revision -m "describe change" --rev-id 0002    # new empty migration
uv run alembic revision --autogenerate -m "..." --rev-id 0002 # draft it from the models (review it!)
```

`--rev-id` keeps ids sequential (`0001`, `0002`, ...) instead of random.
