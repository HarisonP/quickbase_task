"""Tenant-scoped ticket queries. Every function takes the tenant; there is no unscoped access."""

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.models import Tenant, Ticket


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
