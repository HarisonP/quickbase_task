"""Core application settings."""

import os

from sqlalchemy import make_url

DEFAULT_OPENAI_MODEL = "gpt-6-luna"
DEFAULT_DATABASE_URL = "postgresql+psycopg://app:app@localhost:5432/app"
APP_TITLE = "Ticket Assistant"
HOST = "127.0.0.1"
PORT = 8000


def get_database_url() -> str:
    # Read at call time: .env is loaded by uvicorn after this module is first imported.
    return os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)


def get_psycopg_url() -> str:
    """DATABASE_URL without SQLAlchemy's `+psycopg` driver suffix, for plain psycopg (the checkpointer)."""
    return make_url(get_database_url()).set(drivername="postgresql").render_as_string(hide_password=False)
