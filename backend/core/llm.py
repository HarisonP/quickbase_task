"""Shared chat model."""

import os
from functools import lru_cache

from langchain_openai import ChatOpenAI

from backend.core.config import DEFAULT_OPENAI_MODEL


@lru_cache(maxsize=1)
def get_llm() -> ChatOpenAI:
    # Read at call time: .env is loaded by uvicorn after config is first imported.
    return ChatOpenAI(model=os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL))
