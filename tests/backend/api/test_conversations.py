"""Turning the agent's stream updates into the events the chat UI shows."""

from langchain_core.messages import AIMessage, ToolMessage

from backend.api.conversations import final_answer_from, tool_events_from

READ_TICKET_1 = {"id": "call-1", "name": "read_ticket", "args": {"ticket_id": 1}}


def test_a_tool_call_and_its_result_become_trace_events() -> None:
    update = {
        "model": {"messages": [AIMessage("", tool_calls=[READ_TICKET_1])]},
        "tools": {"messages": [ToolMessage("Ticket 1 ...", tool_call_id="call-1", name="read_ticket")]},
    }

    events = tool_events_from(update)

    assert [(event.event, event.data) for event in events] == [
        ("tool_call", {"id": "call-1", "tool": "read_ticket", "args": {"ticket_id": 1}}),
        ("tool_result", {"id": "call-1", "tool": "read_ticket", "content": "Ticket 1 ...", "status": "success"}),
    ]


def test_nodes_without_messages_add_no_events() -> None:
    update = {"HumanInTheLoopMiddleware.after_model": None}

    assert tool_events_from(update) == []


def test_the_final_answer_is_the_ai_text() -> None:
    update = {"model": {"messages": [AIMessage("You have 3 open tickets.")]}}

    assert final_answer_from(update) == "You have 3 open tickets."


def test_a_tool_call_is_not_a_final_answer() -> None:
    update = {"model": {"messages": [AIMessage("Let me check.", tool_calls=[READ_TICKET_1])]}}

    assert final_answer_from(update) is None
