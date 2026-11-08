"""FastAPI application entry point."""

from fastapi import FastAPI

from backend.api import conversations, tickets
from backend.api.routes import router
from backend.app.lifespan import lifespan
from backend.core.config import APP_TITLE

app = FastAPI(title=APP_TITLE, lifespan=lifespan)
app.include_router(router)
app.include_router(tickets.router)
app.include_router(conversations.router)
