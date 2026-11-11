"""One chat turn: the agent's stream as SSE events, what is saved to the history, and how failures show.

No database and no model: the agent is a fake that replays a stream, and saving a message is
replaced with a fake that records it.
"""

import uuid
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import httpx
import openai
import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langgraph.errors import GraphRecursionError
from sqlalchemy.exc import SQLAlchemyError

from backend.api import conversations
from backend.api.conversations import (
    RunOutcome,
    describe_decisions,
    events_from_messages,
    events_from_updates,
    failure_message,
    stream_turn,
)
from backend.core.models import Conversation, MessageRole

pytestmark = pytest.mark.anyio

READ_TICKET_1 = {"id": "call-1", "name": "read_ticket", "args": {"ticket_id": 1}}
CLOSE_TICKET_3 = {"tool": "mutate_ticket", "args": {"ticket_id": 3, "action": "update", "fields": {"status": "closed"}}}


def as_tuples(events: Any) -> list[tuple[str, Any]]:
    return [(event.event, event.data) for event in events]


# --- Translating the stream ----------------------------------------------------------------------


def test_a_text_chunk_becomes_a_token() -> None:
    events = events_from_messages((AIMessageChunk("Hel"), {"langgraph_node": "model"}))

    assert as_tuples(events) == [("token", {"content": "Hel"})]


def test_a_tool_call_chunk_has_no_text_and_no_token() -> None:
    chunk = AIMessageChunk("", tool_call_chunks=[{"name": "read_ticket", "args": "", "id": "call-1", "index": 0}])

    assert as_tuples(events_from_messages((chunk, {}))) == []


def test_a_tool_call_and_its_result_become_trace_events() -> None:
    update = {
        "model": {"messages": [AIMessage("", tool_calls=[READ_TICKET_1])]},
        "tools": {"messages": [ToolMessage("Ticket 1 ...", tool_call_id="call-1", name="read_ticket")]},
    }

    assert as_tuples(events_from_updates(update)) == [
        ("tool_call", {"id": "call-1", "tool": "read_ticket", "args": {"ticket_id": 1}}),
        ("tool_result", {"id": "call-1", "tool": "read_ticket", "content": "Ticket 1 ...", "status": "success"}),
    ]


def test_hooks_that_changed_nothing_and_interrupts_add_no_events() -> None:
    update = {"HumanInTheLoopMiddleware.after_model": None, "__interrupt__": (SimpleNamespace(value={}),)}

    assert as_tuples(events_from_updates(update)) == []


# --- How a run ended -----------------------------------------------------------------------------


def test_a_finished_run_saves_the_answer_and_ends_with_done() -> None:
    outcome = RunOutcome(pending_actions=[], answer="Ticket 3 is open.")
    conversation = Conversation(id=uuid.uuid4(), tenant_id="acme")

    assert outcome.history_text == "Ticket 3 is open."
    assert outcome.end_event(conversation).event == "done"


def test_a_paused_run_saves_the_request_and_ends_with_approval_required() -> None:
    outcome = RunOutcome(pending_actions=[CLOSE_TICKET_3], answer="")
    conversation = Conversation(id=uuid.uuid4(), tenant_id="acme")

    event = outcome.end_event(conversation)

    assert outcome.history_text == "Waiting for your approval:\n- update ticket 3: status=closed"
    assert (event.event, event.data["actions"]) == ("approval_required", [CLOSE_TICKET_3])


def test_decisions_read_as_one_line_per_action() -> None:
    delete_ticket_4 = {"tool": "mutate_ticket", "args": {"ticket_id": 4, "action": "delete"}}

    text = describe_decisions([CLOSE_TICKET_3, delete_ticket_4], ["approve", "reject"])

    assert text == "Approved: update ticket 3: status=closed\nRejected: delete ticket 4"


# --- Failures ------------------------------------------------------------------------------------

REQUEST = httpx.Request("POST", "https://api.openai.com/v1/responses")


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (openai.RateLimitError("slow down", response=httpx.Response(429, request=REQUEST), body=None),
         "Rate limited, try again."),
        (openai.APITimeoutError(request=REQUEST), "LLM provider unreachable."),
        (openai.InternalServerError("boom", response=httpx.Response(500, request=REQUEST), body=None),
         "LLM provider error."),
        (GraphRecursionError("too many steps"), "The agent took too many steps and was stopped. Try a simpler request."),
        (SQLAlchemyError("db down"), "Could not save the conversation."),
        (ValueError("unexpected"), "The agent failed to answer."),
    ],
    ids=["rate-limit", "timeout", "status", "recursion", "database", "anything-else"],
)
def test_each_failure_gets_its_own_message(error: Exception, message: str) -> None:
    assert failure_message(error, uuid.uuid4()) == message


# --- A whole turn --------------------------------------------------------------------------------


class FakeAgent:
    """Replays a `(mode, payload)` stream, then reports the given final state (or raises `error`)."""

    def __init__(self, stream: list[tuple[str, Any]], state: Any, error: Exception | None = None) -> None:
        self.stream = stream
        self.state = state
        self.error = error

    async def astream(self, agent_input: Any, **kwargs: Any) -> AsyncIterator[tuple[str, Any]]:
        for item in self.stream:
            yield item

        if self.error:
            raise self.error

    async def aget_state(self, config: Any) -> Any:
        return self.state


def finished_state(answer: str) -> SimpleNamespace:
    return SimpleNamespace(interrupts=[], values={"messages": [AIMessage(answer)]})


def paused_state(*actions: dict[str, Any]) -> SimpleNamespace:
    requests = [{"name": action["tool"], "args": action["args"]} for action in actions]
    interrupt = SimpleNamespace(value={"action_requests": requests})

    return SimpleNamespace(interrupts=[interrupt], values={"messages": [AIMessage("")]})


@pytest.fixture
def saved(monkeypatch: pytest.MonkeyPatch) -> list[tuple]:
    """Every message the turn saves, as (role, content, actions)."""
    recorded: list[tuple] = []

    async def fake_add_message(db_session: object, conversation_id: uuid.UUID, role: MessageRole, content: str,
                               actions: list | None = None) -> None:
        recorded.append((role, content, actions))

    monkeypatch.setattr(conversations, "add_message", fake_add_message)
    return recorded


async def run_turn(agent: FakeAgent, user_message: str) -> list[tuple[str, Any]]:
    conversation = Conversation(id=uuid.uuid4(), tenant_id="acme")
    events = stream_turn(agent, None, conversation, {"messages": []}, user_message=user_message)

    return as_tuples([event async for event in events])


async def test_a_finished_turn_streams_the_answer_and_saves_both_sides(saved: list[tuple]) -> None:
    agent = FakeAgent(
        stream=[
            ("updates", {"model": {"messages": [AIMessage("", tool_calls=[READ_TICKET_1])]}}),
            ("updates", {"tools": {"messages": [ToolMessage("Ticket 1 ...", tool_call_id="call-1", name="read_ticket")]}}),
            ("messages", (AIMessageChunk("Ticket 1 "), {})),
            ("messages", (AIMessageChunk("is open."), {})),
        ],
        state=finished_state("Ticket 1 is open."),
    )

    events = await run_turn(agent, "How is ticket 1?")

    assert [name for name, _ in events] == ["tool_call", "tool_result", "token", "token", "done"]
    assert saved == [
        (MessageRole.USER, "How is ticket 1?", None),
        (MessageRole.ASSISTANT, "Ticket 1 is open.", None),
    ]


async def test_a_paused_turn_ends_with_the_approval_and_saves_its_actions(saved: list[tuple]) -> None:
    agent = FakeAgent(stream=[("updates", {"__interrupt__": ()})], state=paused_state(CLOSE_TICKET_3))

    events = await run_turn(agent, "Close ticket 3")

    name, data = events[-1]

    assert (name, data["actions"]) == ("approval_required", [CLOSE_TICKET_3])
    assert saved[-1] == (
        MessageRole.ASSISTANT,
        "Waiting for your approval:\n- update ticket 3: status=closed",
        [CLOSE_TICKET_3],
    )


async def test_a_failing_agent_ends_with_an_error_event_and_saves_no_answer(saved: list[tuple]) -> None:
    agent = FakeAgent(
        stream=[("messages", (AIMessageChunk("Let me"), {}))],
        state=finished_state("never read"),
        error=GraphRecursionError("too many steps"),
    )

    events = await run_turn(agent, "Do everything")

    assert events == [
        ("token", {"content": "Let me"}),
        ("error", {"message": "The agent took too many steps and was stopped. Try a simpler request."}),
    ]
    assert saved == [(MessageRole.USER, "Do everything", None)]
