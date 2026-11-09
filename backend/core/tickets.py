"""Tenant-scoped ticket queries. Every function takes the tenant; there is no unscoped access."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.models import Tenant, Ticket, TicketPriority, TicketStatus


class TicketFields(BaseModel):
    """The ticket fields a change may set. Anything else (id, tenant_id, ...) is rejected.

    Shared by the agent's mutate_ticket tool and the board's PATCH endpoint: one set of rules.
    """

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, min_length=1)
    status: TicketStatus | None = None
    priority: TicketPriority | None = None


class NewTicket(BaseModel):
    """The fields of a new ticket. The id, tenant and created_at are set by the server, never by the caller."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1)
    status: TicketStatus = TicketStatus.OPEN
    priority: TicketPriority = TicketPriority.MEDIUM


async def tenant_exists(db_session: AsyncSession, tenant_id: str) -> bool:
    return await db_session.get(Tenant, tenant_id) is not None


async def list_tickets(db_session: AsyncSession, tenant_id: str) -> list[Ticket]:
    result = await db_session.scalars(select(Ticket).where(Ticket.tenant_id == tenant_id).order_by(Ticket.id))
    return list(result)


async def count_tickets(db_session: AsyncSession, tenant_id: str) -> int:
    count = await db_session.scalar(select(func.count()).select_from(Ticket).where(Ticket.tenant_id == tenant_id))
    return count or 0


async def list_ticket_page(db_session: AsyncSession, tenant_id: str, offset: int, limit: int) -> list[Ticket]:
    """Tenant's tickets ordered by id, from position `offset` (0-based), at most `limit`."""
    statement = select(Ticket).where(Ticket.tenant_id == tenant_id).order_by(Ticket.id).offset(offset).limit(limit)
    result = await db_session.scalars(statement)
    return list(result)


async def get_ticket(db_session: AsyncSession, tenant_id: str, ticket_id: int) -> Ticket | None:
    """The ticket, or None if it doesn't exist *or* belongs to another tenant (indistinguishable)."""
    return await db_session.scalar(select(Ticket).where(Ticket.id == ticket_id, Ticket.tenant_id == tenant_id))


async def create_ticket(db_session: AsyncSession, tenant_id: str, fields: NewTicket) -> Ticket:
    """Create a ticket owned by `tenant_id`. The database assigns its id and created_at."""
    ticket = Ticket(tenant_id=tenant_id, **fields.model_dump())
    db_session.add(ticket)
    await db_session.commit()

    # Load the values the database generated (id, created_at).
    await db_session.refresh(ticket)
    return ticket


async def update_ticket(db_session: AsyncSession, tenant_id: str, ticket_id: int, changes: dict[str, Any]) -> bool:
    """Apply `changes` to the ticket. False if it doesn't exist *or* belongs to another tenant.

    The tenant check is part of the UPDATE itself, so there is no gap between checking and writing.
    """
    statement = (
        update(Ticket)
        .where(Ticket.id == ticket_id, Ticket.tenant_id == tenant_id)
        .values(**changes)
        .returning(Ticket.id)
    )
    updated = await db_session.scalar(statement)
    await db_session.commit()
    return updated is not None


async def delete_ticket(db_session: AsyncSession, tenant_id: str, ticket_id: int) -> bool:
    """Delete the ticket. False if it doesn't exist *or* belongs to another tenant."""
    statement = delete(Ticket).where(Ticket.id == ticket_id, Ticket.tenant_id == tenant_id).returning(Ticket.id)
    deleted = await db_session.scalar(statement)
    await db_session.commit()
    return deleted is not None


async def find_tickets(db_session: AsyncSession, tenant_id: str, query: str, limit: int) -> list[Ticket]:
    """Tenant's tickets whose title or description contains `query` (case-insensitive)."""
    statement = select(Ticket).where(Ticket.tenant_id == tenant_id)
    if query.strip():
        # autoescape: % and _ in the query are matched literally, not as wildcards.
        statement = statement.where(
            or_(
                Ticket.title.icontains(query, autoescape=True),
                Ticket.description.icontains(query, autoescape=True),
            )
        )
    result = await db_session.scalars(statement.order_by(Ticket.id).limit(limit))
    return list(result)
