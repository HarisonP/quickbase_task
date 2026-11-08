"""Ticket routes, scoped to the caller's tenant."""

from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, status
from loguru import logger
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.db import get_session
from backend.core.models import TicketPriority, TicketStatus
from backend.core.tickets import list_tickets, tenant_exists

router = APIRouter(prefix="/api/tickets", tags=["tickets"])


class TicketResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str
    status: TicketStatus
    priority: TicketPriority
    created_at: datetime


async def get_tenant_id(x_tenant_id: str = Header(), session: AsyncSession = Depends(get_session)) -> str:
    """Stand-in for real auth: the X-Tenant-ID header names the caller's tenant."""
    if not await tenant_exists(session, x_tenant_id):
        logger.warning("Rejected request for unknown tenant {!r}", x_tenant_id)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown tenant")
    return x_tenant_id


@router.get("")
async def get_tickets(
    tenant_id: str = Depends(get_tenant_id), session: AsyncSession = Depends(get_session)
) -> list[TicketResponse]:
    """All tickets of the caller's tenant."""
    tickets = await list_tickets(session, tenant_id)
    logger.info("Listed {} tickets for tenant {}", len(tickets), tenant_id)
    return [TicketResponse.model_validate(ticket) for ticket in tickets]
