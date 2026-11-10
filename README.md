# Ticket Assistant

A chat agent with tools over a multi-tenant ticket system. Some ticket text is attacker-controlled; it must never
bypass the approval gate or leak data across tenants. FastAPI + LangChain (OpenAI) on Postgres, with a React UI
built on assistant-ui.

## Quick start

```bash
cp .env.example .env            # then set OPENAI_API_KEY
docker compose up --build       # http://localhost:5173
```

This starts Postgres, runs the migrations and imports the seed tickets (the one-off `setup` service), then starts
the backend and the frontend. Pick a tenant in the header and ask "What are my open tickets?". The seeded
prompt-injection tickets are listed in [ATTACK_TICKETS.md](ATTACK_TICKETS.md).

## Architecture

- **Chat:** `POST /api/conversations/{id}/chat` runs a `create_agent` agent and streams SSE (tokens, tool calls,
  tool results). The UI shows the answer and a trace of every tool call.
- **Approval:** when the model calls `mutate_ticket`, `HumanInTheLoopMiddleware` pauses the run *before* the tool
  executes. The Postgres checkpointer saves the run; the UI shows a blocking modal; `POST /resume` continues it.
- **Board:** the user's own edits (drag and drop, edit form, create, delete) go to `/api/tickets` directly, with no
  approval: approval guards the agent, not the user.

## How tool access and authorization are scoped

- **The tenant comes from the request, never the model.** `X-Tenant-ID` (a stand-in for auth) is passed to the
  agent as runtime context. No tool has a tenant argument.
- **Every query filters by tenant in SQL**, including `UPDATE`/`DELETE`, so the model never sees other tenants'
  rows. "Not found" and "another tenant's" get the same answer.
- **Approval is enforced in code**, not the prompt. The modal shows the exact arguments that will run, and only
  allows approve or reject.
- **Changes can't touch ownership:** allowed fields are a closed model (title, description, status, priority).
- **Ticket text is data:** escaped inside `<ticket>` tags, and the prompt says never to follow it.
- **The UI can't leak:** markdown is rendered without HTML or images, so an injected image URL can't send data out.
- **Runs are bounded** by model and tool call limits.

## Tests

Unit tests with no database or LLM, mirroring `backend/`. The key ones: the real agent stops before
`mutate_ticket` runs until approved; tools ignore any tenant in the query; mutating another tenant's ticket only
gets "not found"; ticket text can't break out of its tag.

## With more time

- Real auth (a signed token) instead of a trusted header.
- Integration tests on real Postgres, and an eval that replays the attack tickets against the model.
- Confirm before opening links in answers; live board updates; tool calls in the saved chat history.

## Running locally

```bash
uv sync
uv run poe db                 # start Postgres only (docker compose)
uv run poe migrate            # create our tables (Alembic) + the LangGraph checkpointer's tables
uv run poe import_tickets     # import data/tickets.json (existing ids are skipped)

uv run poe run_server_dev                      # backend on :8000 (http://127.0.0.1:8000/api/health)
cd frontend && npm install && npm run dev      # http://localhost:5173 (proxies /api to :8000)
```

## Checks

```bash
uv run poe lint
uv run poe typecheck
uv run poe test

cd frontend
npm run lint          # Biome: lint + formatting check
npm run format        # Biome: apply fixes and formatting
npm run typecheck
```

## Migrations

Schema changes are managed with [Alembic](https://alembic.sqlalchemy.org): one file per change in
`migrations/versions/`, using `DATABASE_URL`.

```bash
uv run alembic upgrade head                                    # apply pending migrations
uv run alembic downgrade -1                                    # undo the last one
uv run alembic revision -m "describe change" --rev-id 0002     # new empty migration
uv run alembic revision --autogenerate -m "..." --rev-id 0002  # draft it from the models (review it!)
```

`--rev-id` keeps ids sequential (`0001`, `0002`, ...) instead of random.
