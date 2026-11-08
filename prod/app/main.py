"""FastAPI application entry point."""

from fastapi import FastAPI

from prod.api.routes import router
from prod.app.lifespan import lifespan
from prod.core.config import APP_TITLE

app = FastAPI(title=APP_TITLE, lifespan=lifespan)
app.include_router(router)
