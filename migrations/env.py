"""Alembic environment: runs migrations against DATABASE_URL."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from backend.core.config import get_database_url
from backend.core.models import Base

if context.config.config_file_name is not None:
    fileConfig(context.config.config_file_name)

# Alembic runs migrations synchronously; psycopg works for both sync and async engines.
engine = create_engine(get_database_url(), poolclass=pool.NullPool)
with engine.connect() as connection:
    # target_metadata lets `alembic revision --autogenerate` diff the models against the database.
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()
