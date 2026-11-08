"""Tenant-scoped ticket queries. Every function takes the tenant; there is no unscoped access."""

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.models import Tenant, Ticket


async def tenant_exists(session: AsyncSession, tenant_id: str) -> bool:
    return await session.get(Tenant, tenant_id) is not None


async def list_tickets(session: AsyncSession, tenant_id: str) -> list[Ticket]:
    result = await session.scalars(select(Ticket).where(Ticket.tenant_id == tenant_id).order_by(Ticket.id))
    return list(result)


async def find_tickets(session: AsyncSession, tenant_id: str, query: str, limit: int) -> list[Ticket]:
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
    result = await session.scalars(statement.order_by(Ticket.id).limit(limit))
    return list(result)
