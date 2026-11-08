"""HTTP API routes."""

import json
from collections.abc import AsyncIterator
from typing import Any

import openai
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessageChunk, HumanMessage
from langgraph.graph.state import CompiledStateGraph
from loguru import logger
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api")


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)


def get_agent(request: Request) -> CompiledStateGraph:
    agent: CompiledStateGraph = request.app.state.agent
    return agent


def format_event(event: dict[str, Any]) -> str:
    """Encode one event in the Server-Sent Events wire format."""
    return json.dumps(event)


def error_event(content: str) -> str:
    return format_event({"type": "error", "content": content})


async def stream_answer(agent: CompiledStateGraph, message: str) -> AsyncIterator[str]:
    try:
        async for chunk, _metadata in agent.astream(
            {"messages": [HumanMessage(message)]}, stream_mode="messages"
        ):
            if isinstance(chunk, AIMessageChunk) and chunk.text:
                yield format_event({"type": "token", "content": chunk.text})
    except openai.RateLimitError:
        logger.warning("OpenAI rate limit hit")
        yield error_event("Rate limited, try again.")
        return
    except openai.APIConnectionError:
        # Also covers openai.APITimeoutError.
        logger.exception("Could not reach OpenAI")
        yield error_event("LLM provider unreachable.")
        return
    except openai.APIStatusError as error:
        logger.error("OpenAI returned {}: {}", error.status_code, error.message)
        yield error_event("LLM provider error.")
        return
    except Exception:
        
        logger.exception("Agent stream failed")
        yield error_event("The agent failed to answer.")
        return
    yield format_event({"type": "done"})


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/chat")
async def chat(
    body: ChatRequest, agent: CompiledStateGraph = Depends(get_agent)
) -> StreamingResponse:
    return StreamingResponse(
        stream_answer(agent, body.message), media_type="text/event-stream"
    )
