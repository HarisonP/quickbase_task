"""Tools the assistant can call.

Tools raise ToolException for failures. With handle_tool_error=True the message goes back to the
model as an error tool result, so the agent keeps running and can tell the user, instead of the
whole chat stream failing. Messages are short and generic: no internals reach the model.
"""

from html import escape

from langchain.tools import ToolRuntime, tool
from langchain_core.tools import ToolException
from loguru import logger
from sqlalchemy.exc import SQLAlchemyError

from backend.core.agents.context import AgentContext
from backend.core.db import get_sessionmaker
from backend.core.models import Ticket
from backend.core.tickets import find_tickets

SEARCH_LIMIT = 10


def format_ticket(ticket: Ticket) -> str:
    # Escaped, so ticket text cannot close the <ticket> tag and pose as something else.
    return (
        f'<ticket id="{ticket.id}" status="{ticket.status}" priority="{ticket.priority}">\n'
        f"<title>{escape(ticket.title)}</title>\n"
        f"<description>{escape(ticket.description)}</description>\n"
        f"</ticket>"
    )


@tool
async def search_tickets(query: str, runtime: ToolRuntime[AgentContext]) -> str:
    """Search the user's support tickets by words in the title or description.

    Args:
        query: Words to look for. Use an empty string to list the user's tickets.
    """
    # The tenant comes from the server-side context, never from the model's arguments.
    tenant_id = runtime.context.tenant_id
    try:
        async with get_sessionmaker()() as session:
            tickets = await find_tickets(session, tenant_id, query, SEARCH_LIMIT)
    except SQLAlchemyError as error:
        logger.exception("search_tickets database error for tenant {}", tenant_id)
        raise ToolException("Ticket search is unavailable right now. Try again later.") from error
    except Exception as error:
        logger.exception("search_tickets failed for tenant {}", tenant_id)
        raise ToolException("Ticket search failed.") from error
    logger.info(
        "search_tickets tenant={} query={!r} -> ids {}", tenant_id, query, [ticket.id for ticket in tickets]
    )
    if not tickets:
        return "No tickets found."
    return "\n".join(format_ticket(ticket) for ticket in tickets)


# ToolException -> error tool result for the model, instead of crashing the agent run.
search_tickets.handle_tool_error = True
# Arguments that don't match the schema (e.g. query is not a string) -> error tool result too.
search_tickets.handle_validation_error = True
