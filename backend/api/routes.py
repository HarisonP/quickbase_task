"""HTTP API routes."""

from collections.abc import AsyncIterator

import openai
from fastapi import APIRouter, Depends, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.errors import GraphRecursionError
from langgraph.graph.state import CompiledStateGraph
from loguru import logger
from pydantic import BaseModel, Field

from backend.api.tickets import get_tenant_id
from backend.core.agents.context import AgentContext

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
async def chat(
    body: ChatRequest,
    tenant_id: str = Depends(get_tenant_id),
    agent: CompiledStateGraph = Depends(get_agent),
) -> AsyncIterator[ServerSentEvent]:
    """Stream the agent's answer as SSE events: `token`*, then `done` or `error`."""
    logger.info("Chat request from tenant {} ({} chars)", tenant_id, len(body.message))
    try:
        async for chunk, _metadata in agent.astream(
            {"messages": [HumanMessage(body.message)]},
            context=AgentContext(tenant_id=tenant_id),
            stream_mode="messages",
        ):
            # AIMessage also covers AIMessageChunk: streamed tokens, plus whole messages added by
            # middleware (e.g. the closing message when the model call limit ends the run).
            if isinstance(chunk, AIMessage) and chunk.text:
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
    except GraphRecursionError:
        logger.warning("Agent hit the recursion limit for tenant {}", tenant_id)
        yield error_event("The agent took too many steps and was stopped. Try a simpler request.")
        return
    except Exception:
        # Headers (200) are already sent once streaming starts, so report the failure in-band.
        logger.exception("Agent stream failed")
        yield error_event("The agent failed to answer.")
        return
    logger.info("Chat answer finished for tenant {}", tenant_id)
    yield ServerSentEvent(event="done", data={})
