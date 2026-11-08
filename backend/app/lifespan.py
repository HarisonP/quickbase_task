"""Application lifespan: sets up shared resources and releases them on shutdown."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from langfuse import get_client
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from loguru import logger
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from backend.core.agents.assistant import build_assistant
from backend.core.config import get_psycopg_url
from backend.core.db import get_engine
from backend.core.llm import get_llm

# Connection settings the LangGraph Postgres checkpointer requires.
CHECKPOINTER_CONNECTION_KWARGS = {"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Build the agent with its Postgres checkpointer; on shutdown flush traces and close connections."""
    async with AsyncConnectionPool(get_psycopg_url(), kwargs=CHECKPOINTER_CONNECTION_KWARGS, open=False) as pool:
        # Tables are created at deploy time by `poe migrate`, not here.
        app.state.agent = build_assistant(get_llm(), AsyncPostgresSaver(pool))
        logger.info("Assistant ready")
        try:
            yield
        finally:
            # Traces are sent in the background; send what is left before exiting.
            get_client().shutdown()
            await get_engine().dispose()
            logger.info("Application stopped")
