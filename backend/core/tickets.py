"""Tenant-scoped ticket queries. Every function takes the tenant; there is no unscoped access."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.models import Tenant, Ticket


async def tenant_exists(session: AsyncSession, tenant_id: str) -> bool:
    return await session.get(Tenant, tenant_id) is not None


async def list_tickets(session: AsyncSession, tenant_id: str) -> list[Ticket]:
    result = await session.scalars(select(Ticket).where(Ticket.tenant_id == tenant_id).order_by(Ticket.id))
    return list(result)
