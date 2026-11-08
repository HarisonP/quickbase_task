"""Conversation routes: create, list, history, and chat (SSE). All scoped to the caller's tenant."""

import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import openai
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.sse import EventSourceResponse, ServerSentEvent
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.errors import GraphRecursionError
from langgraph.graph.state import CompiledStateGraph
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.dependencies import get_agent, get_tenant_id
from backend.core.agents.context import AgentContext
from backend.core.conversations import (
    add_message,
    create_conversation,
    get_conversation,
    list_conversations,
    list_messages,
)
from backend.core.db import get_session
from backend.core.models import Conversation, MessageRole

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    role: MessageRole
    content: str
    created_at: datetime


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)


async def get_owned_conversation(
    conversation_id: uuid.UUID,
    tenant_id: str = Depends(get_tenant_id),
    db_session: AsyncSession = Depends(get_session),
) -> Conversation:
    """The conversation from the path, if it belongs to the caller's tenant. 404 otherwise."""
    conversation = await get_conversation(db_session, tenant_id, conversation_id)
    if conversation is None:
        # Same answer for "doesn't exist" and "another tenant's": no hint that the id exists.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    return conversation


def error_event(message: str) -> ServerSentEvent:
    return ServerSentEvent(event="error", data={"message": message})


def final_answer_from(update: dict[str, Any]) -> str | None:
    """The text of the last finished AI answer in an `updates` event, if there is one.

    An `updates` event maps node name -> that node's output. A finished answer is an AIMessage with
    text and no tool calls (an AIMessage *with* tool calls means the agent continues with tools).
    """
    answer = None
    for node_output in update.values():
        if not isinstance(node_output, dict):
            continue
        for message in node_output.get("messages", []):
            if isinstance(message, AIMessage) and message.text and not message.tool_calls:
                answer = message.text
    return answer


async def stream_run(
    agent: CompiledStateGraph,
    db_session: AsyncSession,
    conversation: Conversation,
    agent_input: Any,
    user_message: str | None,
) -> AsyncIterator[ServerSentEvent]:
    """Run the agent on the conversation's thread and stream it as SSE: `token`*, then `done` or `error`.

    Saves `user_message` first (if given) and the final answer once the run finishes, using the
    request's database session. (Tools open their own: parallel tool calls must not share one.)
    """
    tenant_id = conversation.tenant_id
    config: RunnableConfig = {
        # The conversation id is the LangGraph thread: the checkpointer keeps its state under it.
        "configurable": {"thread_id": str(conversation.id)},
        # Groups the conversation's runs in Langfuse.
        "metadata": {"langfuse_session_id": str(conversation.id), "langfuse_user_id": tenant_id},
    }
    final_answer: str | None = None
    try:
        if user_message is not None:
            await add_message(db_session, conversation.id, MessageRole.USER, user_message)
        # Two modes at once: "messages" for tokens as they are generated, "updates" for each node's
        # complete output (the whole final message; in 3b also the approval interrupt).
        async for mode, payload in agent.astream(
            agent_input,
            config=config,
            context=AgentContext(tenant_id=tenant_id),
            stream_mode=["messages", "updates"],
        ):
            if mode == "messages":
                chunk, _metadata = payload
                # AIMessage also covers AIMessageChunk: streamed tokens, plus whole messages added by
                # middleware (e.g. the closing message when the model call limit ends the run).
                if isinstance(chunk, AIMessage) and chunk.text:
                    yield ServerSentEvent(event="token", data={"content": chunk.text})
            elif mode == "updates":
                final_answer = final_answer_from(payload) or final_answer
        if final_answer is not None:
            await add_message(db_session, conversation.id, MessageRole.ASSISTANT, final_answer)
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
        logger.warning("Agent hit the recursion limit in conversation {}", conversation.id)
        yield error_event("The agent took too many steps and was stopped. Try a simpler request.")
        return
    except SQLAlchemyError:
        logger.exception("Database error in conversation {}", conversation.id)
        yield error_event("Could not save the conversation.")
        return
    except Exception:
        # Headers (200) are already sent once streaming starts, so report the failure in-band.
        logger.exception("Agent stream failed in conversation {}", conversation.id)
        yield error_event("The agent failed to answer.")
        return
    logger.info("Chat answer finished in conversation {} (tenant {})", conversation.id, tenant_id)
    yield ServerSentEvent(event="done", data={})


@router.post("", status_code=status.HTTP_201_CREATED)
async def start_conversation(
    tenant_id: str = Depends(get_tenant_id), db_session: AsyncSession = Depends(get_session)
) -> ConversationResponse:
    conversation = await create_conversation(db_session, tenant_id)
    logger.info("Created conversation {} for tenant {}", conversation.id, tenant_id)
    return ConversationResponse.model_validate(conversation)


@router.get("")
async def get_conversations(
    tenant_id: str = Depends(get_tenant_id), db_session: AsyncSession = Depends(get_session)
) -> list[ConversationResponse]:
    """The caller's conversations, newest first."""
    conversations = await list_conversations(db_session, tenant_id)
    return [ConversationResponse.model_validate(conversation) for conversation in conversations]


@router.get("/{conversation_id}/messages")
async def get_messages(
    conversation: Conversation = Depends(get_owned_conversation), db_session: AsyncSession = Depends(get_session)
) -> list[MessageResponse]:
    """Chat history: the user's messages and the agent's final answers, in order."""
    messages = await list_messages(db_session, conversation.tenant_id, conversation.id)
    return [MessageResponse.model_validate(message) for message in messages]


@router.post("/{conversation_id}/chat", response_class=EventSourceResponse)
async def chat(
    body: ChatRequest,
    conversation: Conversation = Depends(get_owned_conversation),
    db_session: AsyncSession = Depends(get_session),
    agent: CompiledStateGraph = Depends(get_agent),
) -> AsyncIterator[ServerSentEvent]:
    """Send a message and stream the answer as SSE events: `token`*, then `done` or `error`."""
    logger.info(
        "Chat message in conversation {} (tenant {}, {} chars)",
        conversation.id, conversation.tenant_id, len(body.message),
    )
    # Only the new message: the checkpointer already holds the conversation's earlier messages.
    agent_input = {"messages": [HumanMessage(body.message)]}
    async for event in stream_run(agent, db_session, conversation, agent_input, user_message=body.message):
        yield event
