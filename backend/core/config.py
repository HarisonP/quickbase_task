"""Core application settings."""

import os

DEFAULT_OPENAI_MODEL = "gpt-6-luna"
DEFAULT_DATABASE_URL = "postgresql+psycopg://app:app@localhost:5432/app"
APP_TITLE = "Python Service"
HOST = "127.0.0.1"
PORT = 8000


def get_database_url() -> str:
    # Read at call time: .env is loaded by uvicorn after this module is first imported.
    return os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
