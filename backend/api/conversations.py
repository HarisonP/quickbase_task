"""Conversation routes: create, list, history, chat and approval resume (SSE). All tenant-scoped."""

import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any, Literal

import openai
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.sse import EventSourceResponse, ServerSentEvent
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.errors import GraphRecursionError
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command
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


class ResumeRequest(BaseModel):
    # One decision per pending action, in the order of the `approval_required` event's actions.
    decisions: list[Literal["approve", "reject"]] = Field(min_length=1)


REJECTION_MESSAGE = "The user chose not to make this change, so it was not applied."


def thread_config(conversation: Conversation) -> RunnableConfig:
    return {
        # The conversation id is the LangGraph thread: the checkpointer keeps its state under it.
        "configurable": {"thread_id": str(conversation.id)},
        # Groups the conversation's runs in Langfuse.
        "metadata": {"langfuse_session_id": str(conversation.id), "langfuse_user_id": conversation.tenant_id},
    }


def actions_from(interrupt_value: dict[str, Any]) -> list[dict[str, Any]]:
    """The tool calls waiting for approval, from HumanInTheLoopMiddleware's interrupt payload.

    These are the model's real tool name and arguments, exactly what will run if approved.
    """
    return [{"tool": request["name"], "args": request["args"]} for request in interrupt_value["action_requests"]]


def describe_action(action: dict[str, Any]) -> str:
    """One readable line for the chat history, e.g. "update ticket 3: status=open"."""
    args = action["args"]
    if action["tool"] != "mutate_ticket":
        return f"{action['tool']} {args}"
    fields = ", ".join(f"{name}={value}" for name, value in (args.get("fields") or {}).items())
    line = f"{args.get('action')} ticket {args.get('ticket_id')}"
    return f"{line}: {fields}" if fields else line


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


async def pending_actions(agent: CompiledStateGraph, conversation: Conversation) -> list[dict[str, Any]]:
    """Tool calls the conversation's paused run is waiting to have approved (empty if none)."""
    state = await agent.aget_state(thread_config(conversation))
    return [action for interrupt in state.interrupts for action in actions_from(interrupt.value)]


async def require_pending_approval(
    conversation: Conversation = Depends(get_owned_conversation), agent: CompiledStateGraph = Depends(get_agent)
) -> list[dict[str, Any]]:
    """The pending actions; 409 if nothing is waiting for approval."""
    actions = await pending_actions(agent, conversation)
    if not actions:
        raise HTTPException(status.HTTP_409_CONFLICT, "Nothing is waiting for approval.")
    return actions


def error_event(message: str) -> ServerSentEvent:
    return ServerSentEvent(event="error", data={"message": message})


def approval_event(conversation: Conversation, actions: list[dict[str, Any]]) -> ServerSentEvent:
    return ServerSentEvent(
        event="approval_required", data={"conversation_id": str(conversation.id), "actions": actions}
    )


def tool_events_from(update: dict[str, Any]) -> list[ServerSentEvent]:
    """The tool-call trace in an `updates` event: what the model called, and what came back.

    Scans every node, not just "tools": middleware also adds tool results (a rejected approval,
    a call blocked by a tool call limit). The same call can show up twice (the approval middleware
    re-emits the model's message), so clients key calls by id.
    """
    events = []
    for node_output in update.values():
        if not isinstance(node_output, dict):
            continue
        for message in node_output.get("messages", []):
            if isinstance(message, AIMessage):
                events.extend(
                    ServerSentEvent(
                        event="tool_call", data={"id": call["id"], "tool": call["name"], "args": call["args"]}
                    )
                    for call in message.tool_calls
                )
            elif isinstance(message, ToolMessage):
                events.append(
                    ServerSentEvent(
                        event="tool_result",
                        data={
                            "id": message.tool_call_id,
                            "tool": message.name,
                            "content": message.text,
                            "status": message.status,
                        },
                    )
                )
    return events


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
    """Run the agent on the conversation's thread and stream it as SSE events:
    `token`, `tool_call` and `tool_result` as they happen, then one of `done`,
    `approval_required` (the run paused) or `error`.

    Saves `user_message` first (if given) and the final answer once the run finishes, using the
    request's database session. (Tools open their own: parallel tool calls must not share one.)
    """
    tenant_id = conversation.tenant_id
    final_answer: str | None = None
    approval_actions: list[dict[str, Any]] = []
    try:
        if user_message is not None:
            await add_message(db_session, conversation.id, MessageRole.USER, user_message)
        # Two modes at once: "messages" for tokens as they are generated, "updates" for each node's
        # complete output (the whole final message, and the approval interrupt).
        async for mode, payload in agent.astream(
            agent_input,
            config=thread_config(conversation),
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
                if "__interrupt__" in payload:
                    # HumanInTheLoopMiddleware paused the run before mutate_ticket executes.
                    for interrupt in payload["__interrupt__"]:
                        approval_actions.extend(actions_from(interrupt.value))
                else:
                    for event in tool_events_from(payload):
                        yield event
                    final_answer = final_answer_from(payload) or final_answer
        if approval_actions:
            # Paused: save the approval request, so the history shows what was asked. The final
            # answer comes (and is saved) after the resume.
            request = "Waiting for your approval:\n" + "\n".join(f"- {describe_action(a)}" for a in approval_actions)
            await add_message(db_session, conversation.id, MessageRole.ASSISTANT, request)
        elif final_answer is not None:
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
    if approval_actions:
        logger.info(
            "Conversation {} (tenant {}) waits for approval of {}", conversation.id, tenant_id, approval_actions
        )
        yield approval_event(conversation, approval_actions)
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
    """Send a message and stream the answer (see `stream_run` for the events).

    While an approval is pending, answers with the same `approval_required` event again and ignores
    the message: running the agent would leave the paused tool call unanswered.
    """
    actions = await pending_actions(agent, conversation)
    if actions:
        logger.info("Conversation {} still waits for approval; re-sending it", conversation.id)
        yield approval_event(conversation, actions)
        return
    logger.info(
        "Chat message in conversation {} (tenant {}, {} chars)",
        conversation.id, conversation.tenant_id, len(body.message),
    )
    # Only the new message: the checkpointer already holds the conversation's earlier messages.
    agent_input = {"messages": [HumanMessage(body.message)]}
    async for event in stream_run(agent, db_session, conversation, agent_input, user_message=body.message):
        yield event


@router.post("/{conversation_id}/resume", response_class=EventSourceResponse)
async def resume(
    body: ResumeRequest,
    conversation: Conversation = Depends(get_owned_conversation),
    actions: list[dict[str, Any]] = Depends(require_pending_approval),
    db_session: AsyncSession = Depends(get_session),
    agent: CompiledStateGraph = Depends(get_agent),
) -> AsyncIterator[ServerSentEvent]:
    """Approve or reject the pending actions and stream the rest of the run.

    The client sends only decisions. What runs on approve are the tool calls stored in the server's
    checkpoint, so a client cannot change the arguments.
    """
    if len(body.decisions) != len(actions):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"Expected {len(actions)} decisions, got {len(body.decisions)}."
        )
    logger.info(
        "Resume in conversation {} (tenant {}): {} for {}",
        conversation.id, conversation.tenant_id, body.decisions, actions,
    )
    decisions = [
        {"type": "approve"} if decision == "approve" else {"type": "reject", "message": REJECTION_MESSAGE}
        for decision in body.decisions
    ]
    agent_input = Command(resume={"decisions": decisions})
    async for event in stream_run(agent, db_session, conversation, agent_input, user_message=None):
        yield event
