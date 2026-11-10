# The backend image. compose.yaml uses it twice: `setup` (migrations + seed data) and `backend` (the API).
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PATH="/app/.venv/bin:$PATH"

# Dependencies first: this layer is cached until pyproject.toml or uv.lock change.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY README.md alembic.ini ./
COPY backend backend
COPY migrations migrations
COPY data data
RUN uv sync --frozen --no-dev

EXPOSE 8000
CMD ["python", "-m", "backend.app.application", "--host", "0.0.0.0"]
