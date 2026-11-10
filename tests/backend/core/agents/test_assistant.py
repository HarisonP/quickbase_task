"""The approval gate: mutate_ticket runs only after the user approves it.

The real agent, driven by a scripted model that asks to delete ticket 1, then answers "Done.".
"""

from contextlib import asynccontextmanager

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from backend.core.agents import tools
from backend.core.agents.assistant import build_assistant
from backend.core.agents.context import AgentContext

pytestmark = pytest.mark.anyio

CONFIG = {"configurable": {"thread_id": "test-thread"}}
CONTEXT = AgentContext("acme")
DELETE_TICKET_1 = {"id": "call-1", "name": "mutate_ticket", "args": {"ticket_id": 1, "action": "delete"}}


class ScriptedModel(GenericFakeChatModel):
    """Replies with the given messages in order."""

    def bind_tools(self, tools, **kwargs):
        return self


@pytest.fixture
def deleted(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Ids of the tickets the tool deleted (in a fake database)."""
    deleted_ids: list[int] = []

    @asynccontextmanager
    async def fake_session(tool_name: str, tenant_id: str):
        yield None

    async def fake_delete(db_session: object, tenant_id: str, ticket_id: int) -> bool:
        deleted_ids.append(ticket_id)
        return True

    monkeypatch.setattr(tools, "tool_session", fake_session)
    monkeypatch.setattr(tools, "delete_ticket", fake_delete)
    return deleted_ids


@pytest.fixture
def agent():
    model = ScriptedModel(messages=iter([AIMessage("", tool_calls=[DELETE_TICKET_1]), AIMessage("Done.")]))
    return build_assistant(model, InMemorySaver())


async def ask(agent, message: str) -> dict:
    return await agent.ainvoke({"messages": [("user", message)]}, CONFIG, context=CONTEXT)


async def decide(agent, decision: str) -> dict:
    return await agent.ainvoke(Command(resume={"decisions": [{"type": decision}]}), CONFIG, context=CONTEXT)


async def test_the_run_pauses_before_the_delete(agent, deleted: list[int]) -> None:
    result = await ask(agent, "Delete ticket 1")

    assert result["__interrupt__"]
    assert deleted == []


async def test_approving_runs_the_delete(agent, deleted: list[int]) -> None:
    await ask(agent, "Delete ticket 1")

    await decide(agent, "approve")

    assert deleted == [1]


async def test_rejecting_never_runs_the_delete(agent, deleted: list[int]) -> None:
    await ask(agent, "Delete ticket 1")

    await decide(agent, "reject")

    assert deleted == []
