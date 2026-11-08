"""FastAPI application entry point."""

from fastapi import FastAPI

from backend.api.routes import router
from backend.app.lifespan import lifespan
from backend.core.config import APP_TITLE

app = FastAPI(title=APP_TITLE, lifespan=lifespan)
app.include_router(router)
