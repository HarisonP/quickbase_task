"""Conversation routes: create, list, history, chat and approval resume (SSE). All tenant-scoped."""

import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

import openai
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.sse import EventSourceResponse, ServerSentEvent
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolCall, ToolMessage
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
    delete_conversation,
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


def failure_message(error: Exception, conversation_id: uuid.UUID) -> str:
    """Log a failed run and return the message for the client's `error` event.

    Most specific first: the order matters where classes overlap (RateLimitError is an
    APIStatusError, APITimeoutError an APIConnectionError). Anything unexpected falls to the end.
    """
    match error:
        case openai.RateLimitError():
            logger.warning("OpenAI rate limit hit")
            return "Rate limited, try again."
        case openai.APIConnectionError():
            logger.opt(exception=error).error("Could not reach OpenAI")
            return "LLM provider unreachable."
        case openai.APIStatusError(status_code=code, message=message):
            logger.error("OpenAI returned {}: {}", code, message)
            return "LLM provider error."
        case GraphRecursionError():
            logger.warning("Agent hit the recursion limit in conversation {}", conversation_id)
            return "The agent took too many steps and was stopped. Try a simpler request."
        case SQLAlchemyError():
            logger.opt(exception=error).error("Database error in conversation {}", conversation_id)
            return "Could not save the conversation."
        case _:
            logger.opt(exception=error).error("Agent stream failed in conversation {}", conversation_id)
            return "The agent failed to answer."


def approval_event(conversation: Conversation, actions: list[dict[str, Any]]) -> ServerSentEvent:
    return ServerSentEvent(
        event="approval_required", data={"conversation_id": str(conversation.id), "actions": actions}
    )


def token_event(text: str) -> ServerSentEvent:
    return ServerSentEvent(event="token", data={"content": text})


def tool_call_event(call: ToolCall) -> ServerSentEvent:
    return ServerSentEvent(event="tool_call", data={"id": call["id"], "tool": call["name"], "args": call["args"]})


def tool_result_event(message: ToolMessage) -> ServerSentEvent:
    return ServerSentEvent(
        event="tool_result",
        data={"id": message.tool_call_id, "tool": message.name, "content": message.text, "status": message.status},
    )


def events_from_messages(payload: tuple[BaseMessage, dict[str, Any]]) -> Iterator[ServerSentEvent]:
    """`messages` mode, payload is (chunk, metadata): text chunks become `token` events.

    AIMessage also covers AIMessageChunk: streamed tokens, plus whole messages a node wrote without
    streaming (e.g. the closing message when the model call limit ends the run).
    """
    chunk, _metadata = payload
    if isinstance(chunk, AIMessage) and chunk.text:
        yield token_event(chunk.text)


def events_from_updates(payload: dict[str, Any]) -> Iterator[ServerSentEvent]:
    """`updates` mode, payload is {node name: node output}: the tool calls and their results.

    Scans every node, not just "tools": middleware also adds tool results (a rejected approval,
    a call blocked by a tool call limit). The same call can show up twice (the approval middleware
    re-emits the model's message), so clients key calls by id.
    """
    for output in payload.values():
        if not isinstance(output, dict):  # None (a hook changed nothing) or the interrupt tuple
            continue

        for message in output.get("messages", []):
            match message:
                case AIMessage(tool_calls=calls):
                    yield from map(tool_call_event, calls)
                case ToolMessage():
                    yield tool_result_event(message)


# Open for extension: a new stream mode (e.g. "custom" for progress) is one translator + one entry.
STREAM_TRANSLATORS = {"messages": events_from_messages, "updates": events_from_updates}


async def run_agent(
    agent: CompiledStateGraph, conversation: Conversation, agent_input: Any
) -> AsyncIterator[ServerSentEvent]:
    """Runs the agent on the conversation's thread, yielding its progress as SSE events."""
    async for mode, payload in agent.astream(
        agent_input,
        config=thread_config(conversation),
        context=AgentContext(tenant_id=conversation.tenant_id),
        stream_mode=list(STREAM_TRANSLATORS),
    ):
        for event in STREAM_TRANSLATORS[mode](payload):
            yield event


@dataclass(frozen=True)
class RunOutcome:
    """How a run ended: paused on tool calls waiting for approval, or finished with an answer."""

    pending_actions: list[dict[str, Any]]
    answer: str

    @property
    def paused(self) -> bool:
        return bool(self.pending_actions)

    @property
    def history_text(self) -> str:
        """What the chat history keeps: the approval request if paused (the answer comes, and is
        saved, after the resume), else the answer."""
        if self.paused:
            return "Waiting for your approval:\n" + "\n".join(f"- {describe_action(a)}" for a in self.pending_actions)
        return self.answer

    def end_event(self, conversation: Conversation) -> ServerSentEvent:
        """The stream's last event."""
        if self.paused:
            return approval_event(conversation, self.pending_actions)
        return ServerSentEvent(event="done", data={})


async def outcome_of(agent: CompiledStateGraph, conversation: Conversation) -> RunOutcome:
    """Reads how the last run ended from the conversation's checkpoint."""
    state = await agent.aget_state(thread_config(conversation))

    return RunOutcome(
        pending_actions=[action for interrupt in state.interrupts for action in actions_from(interrupt.value)],
        answer=state.values["messages"][-1].text,
    )


async def save_user_message(db_session: AsyncSession, conversation: Conversation, text: str | None) -> None:
    if text is not None:
        await add_message(db_session, conversation.id, MessageRole.USER, text)


async def save_outcome(db_session: AsyncSession, conversation: Conversation, outcome: RunOutcome) -> None:
    if outcome.history_text:
        await add_message(db_session, conversation.id, MessageRole.ASSISTANT, outcome.history_text)


async def stream_turn(
    agent: CompiledStateGraph,
    db_session: AsyncSession,
    conversation: Conversation,
    agent_input: Any,
    user_message: str | None,
) -> AsyncIterator[ServerSentEvent]:
    """One chat turn as SSE: `token`, `tool_call` and `tool_result` while the agent runs, then
    `done`, `approval_required` (the run paused) or `error`.

    Saves to the history with the request's database session. (Tools open their own: parallel
    tool calls must not share one.)
    """
    try:
        await save_user_message(db_session, conversation, user_message)

        async for event in run_agent(agent, conversation, agent_input):
            yield event

        outcome = await outcome_of(agent, conversation)
        await save_outcome(db_session, conversation, outcome)
    except Exception as error:
        # Headers (200) are already sent once streaming starts, so report the failure in-band.
        yield error_event(failure_message(error, conversation.id))
    else:
        logger.info(
            "Run in conversation {} (tenant {}) {}",
            conversation.id, conversation.tenant_id, "paused for approval" if outcome.paused else "finished",
        )
        yield outcome.end_event(conversation)


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


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_conversation(
    conversation: Conversation = Depends(get_owned_conversation),
    db_session: AsyncSession = Depends(get_session),
    agent: CompiledStateGraph = Depends(get_agent),
) -> None:
    """Delete the conversation: its messages, and the agent's saved state for it (the LangGraph thread)."""
    # The checkpoint first: if that fails, the conversation is still listed and can be deleted again.
    await agent.checkpointer.adelete_thread(str(conversation.id))
    await delete_conversation(db_session, conversation.tenant_id, conversation.id)

    logger.info("Deleted conversation {} (tenant {})", conversation.id, conversation.tenant_id)


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
    """Send a message and stream the answer (see `stream_turn` for the events).

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
    async for event in stream_turn(agent, db_session, conversation, agent_input, user_message=body.message):
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
    async for event in stream_turn(agent, db_session, conversation, agent_input, user_message=None):
        yield event
