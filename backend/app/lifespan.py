"""Application lifespan: sets up shared resources and releases them on shutdown."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from langfuse import get_client
from loguru import logger

from backend.core.agents.assistant import build_assistant
from backend.core.db import get_engine
from backend.core.llm import get_llm


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Build the agent on startup and flush pending Langfuse traces on shutdown."""
    app.state.agent = build_assistant(get_llm())
    logger.info("Assistant ready")
    try:
        yield
    finally:
        # Traces are sent in the background; send what is left before exiting.
        get_client().shutdown()
        await get_engine().dispose()
        logger.info("Application stopped")
