"""Tools the assistant can call.

Every tool reads the tenant from the server-side runtime context, never from its arguments.

Tools raise ToolException for failures. With handle_tool_error=True the message goes back to the
model as an error tool result, so the agent keeps running and can tell the user, instead of the
whole chat stream failing. Messages are short and generic: no internals reach the model.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from html import escape
from typing import Literal

from langchain.tools import ToolRuntime, tool
from langchain_core.tools import BaseTool, ToolException
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.agents.context import AgentContext
from backend.core.db import get_sessionmaker
from backend.core.models import Ticket, TicketPriority, TicketStatus
from backend.core.tickets import (
    count_tickets,
    delete_ticket,
    find_tickets,
    get_ticket,
    list_ticket_page,
    update_ticket,
)

SEARCH_LIMIT = 10
LIST_PAGE_SIZE = 20


@asynccontextmanager
async def tool_session(tool_name: str, tenant_id: str) -> AsyncGenerator[AsyncSession]:
    """A database session whose failures become ToolExceptions the model can read."""
    try:
        async with get_sessionmaker()() as db_session:
            yield db_session
    except ToolException:
        raise
    except SQLAlchemyError as error:
        logger.exception("{} database error for tenant {}", tool_name, tenant_id)
        raise ToolException(f"{tool_name} is unavailable right now. Try again later.") from error
    except Exception as error:
        logger.exception("{} failed for tenant {}", tool_name, tenant_id)
        raise ToolException(f"{tool_name} failed.") from error


def format_ticket(ticket: Ticket) -> str:
    # Escaped, so ticket text cannot close the <ticket> tag and pose as something else.
    return (
        f'<ticket id="{ticket.id}" status="{ticket.status}" priority="{ticket.priority}">\n'
        f"<title>{escape(ticket.title)}</title>\n"
        f"<description>{escape(ticket.description)}</description>\n"
        f"</ticket>"
    )


def format_ticket_title(index: int, ticket: Ticket) -> str:
    return (
        f'<ticket index="{index}" id="{ticket.id}" status="{ticket.status}" priority="{ticket.priority}">'
        f"{escape(ticket.title)}</ticket>"
    )


@tool
async def search_tickets(query: str, runtime: ToolRuntime[AgentContext]) -> str:
    """Search the user's support tickets by words in the title or description.

    Args:
        query: Words to look for. Use an empty string to list the user's tickets.
    """
    tenant_id = runtime.context.tenant_id
    async with tool_session("search_tickets", tenant_id) as db_session:
        tickets = await find_tickets(db_session,tenant_id, query, SEARCH_LIMIT)
    logger.info(
        "search_tickets tenant={} query={!r} -> ids {}", tenant_id, query, [ticket.id for ticket in tickets]
    )
    if not tickets:
        return "No tickets found."
    return "\n".join(format_ticket(ticket) for ticket in tickets)


@tool
async def list_tickets(runtime: ToolRuntime[AgentContext], start_ticket: int = 0, end_ticket: int = 20) -> str:
    """List the titles of the user's tickets, a page at a time, with the total count.

    Tickets are numbered by index from 0, in a stable order. Returns at most 20 per call; use
    the indexes in the result to ask for the next page. Use read_ticket to see a ticket's details.

    Args:
        start_ticket: Index of the first ticket to list (inclusive), from 0.
        end_ticket: Index to stop before (exclusive). At most start_ticket + 20.
    """
    if start_ticket < 0 or end_ticket <= start_ticket:
        raise ToolException("start_ticket must be >= 0 and end_ticket must be greater than start_ticket.")
    
    tenant_id = runtime.context.tenant_id
    end = min(end_ticket, start_ticket + LIST_PAGE_SIZE)
    async with tool_session("list_tickets", tenant_id) as db_session:
        total = await count_tickets(db_session,tenant_id)
        tickets = await list_ticket_page(db_session,tenant_id, offset=start_ticket, limit=end - start_ticket)
    logger.info(
        "list_tickets tenant={} range={}-{} total={} -> ids {}",
        tenant_id, start_ticket, end, total, [ticket.id for ticket in tickets],
    )

    if not tickets:
        return f"No tickets from index {start_ticket}. Total tickets: {total}."
    
    last = start_ticket + len(tickets)
    header = f"Tickets {start_ticket}-{last - 1} of {total} total."
    if last < total:
        header += f" More available: call list_tickets with start_ticket={last}."
    
    lines = [format_ticket_title(start_ticket + offset, ticket) for offset, ticket in enumerate(tickets)]
    return "\n".join([header, *lines])


@tool
async def read_ticket(ticket_id: int, runtime: ToolRuntime[AgentContext]) -> str:
    """Read one of the user's tickets in full: title, description, status and priority.

    Args:
        ticket_id: The ticket id (the `id` attribute, not the list index).
    """
    tenant_id = runtime.context.tenant_id
    async with tool_session("read_ticket", tenant_id) as db_session:
        ticket = await get_ticket(db_session,tenant_id, ticket_id)
    logger.info("read_ticket tenant={} id={} -> {}", tenant_id, ticket_id, "found" if ticket else "not found")
    
    if ticket is None:
        # Same answer for "doesn't exist" and "another tenant's": no hint that other tenants' ids exist.
        return f"Ticket {ticket_id} not found."
    return format_ticket(ticket)


class TicketFields(BaseModel):
    """The ticket fields an update may change. Anything else (id, tenant_id, ...) is rejected."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, min_length=1)
    status: TicketStatus | None = None
    priority: TicketPriority | None = None


@tool
async def mutate_ticket(
    ticket_id: int,
    action: Literal["update", "delete"],
    runtime: ToolRuntime[AgentContext],
    fields: TicketFields | None = None,
) -> str:
    """Update or delete one of the user's tickets. The user must approve every call before it runs.

    Args:
        ticket_id: The ticket id (the `id` attribute, not the list index).
        action: "update" to change fields, "delete" to remove the ticket.
        fields: For "update" only: the fields to change and their new values.
    """
    # Runs only after the user approved it (HumanInTheLoopMiddleware pauses the agent before this).
    changes = fields.model_dump(exclude_none=True) if fields else {}
    if action == "update" and not changes:
        raise ToolException("An update needs at least one field to change.")
    if action == "delete" and changes:
        raise ToolException("A delete takes no fields.")
        
    tenant_id = runtime.context.tenant_id
    async with tool_session("mutate_ticket", tenant_id) as db_session:
        # The tenant check is inside the UPDATE/DELETE: another tenant's ticket matches no row.
        if action == "update":
            done = await update_ticket(db_session, tenant_id, ticket_id, changes)
        else:
            done = await delete_ticket(db_session, tenant_id, ticket_id)
    
    logger.info(
        "mutate_ticket tenant={} id={} action={} fields={} -> {}",
        tenant_id, ticket_id, action, sorted(changes), "done" if done else "not found",
    )

    if not done:
        # Same answer as read_ticket for "doesn't exist" and "another tenant's".
        return f"Ticket {ticket_id} not found."
    if action == "delete":
        return f"Ticket {ticket_id} deleted."
    return f"Ticket {ticket_id} updated: {', '.join(sorted(changes))}."


TOOLS: list[BaseTool] = [search_tickets, list_tickets, read_ticket, mutate_ticket]

for _tool in TOOLS:
    # ToolException -> error tool result for the model, instead of crashing the agent run.
    _tool.handle_tool_error = True
    # Arguments that don't match the schema (e.g. a non-integer id) -> error tool result too.
    _tool.handle_validation_error = True
