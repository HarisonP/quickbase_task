"""HTTP API routes."""

from collections.abc import AsyncIterator

import openai
from fastapi import APIRouter, Depends, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent
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


def error_event(message: str) -> ServerSentEvent:
    return ServerSentEvent(event="error", data={"message": message})


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/chat", response_class=EventSourceResponse)
async def chat(body: ChatRequest, agent: CompiledStateGraph = Depends(get_agent)) -> AsyncIterator[ServerSentEvent]:
    """Stream the agent's answer as SSE events: `token`*, then `done` or `error`."""
    try:
        async for chunk, _metadata in agent.astream({"messages": [HumanMessage(body.message)]}, stream_mode="messages"):
            if isinstance(chunk, AIMessageChunk) and chunk.text:
                yield ServerSentEvent(event="token", data={"content": chunk.text})
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
        # Headers (200) are already sent once streaming starts, so report the failure in-band.
        logger.exception("Agent stream failed")
        yield error_event("The agent failed to answer.")
        return
    yield ServerSentEvent(event="done", data={})
