"""Ticket routes, scoped to the caller's tenant."""

from datetime import datetime

from fastapi import APIRouter, Depends
from loguru import logger
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.dependencies import get_tenant_id
from backend.core.db import get_session
from backend.core.models import TicketPriority, TicketStatus
from backend.core.tickets import list_tickets

router = APIRouter(prefix="/api/tickets", tags=["tickets"])


class TicketResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str
    status: TicketStatus
    priority: TicketPriority
    created_at: datetime


@router.get("")
async def get_tickets(
    tenant_id: str = Depends(get_tenant_id), db_session: AsyncSession = Depends(get_session)
) -> list[TicketResponse]:
    """All tickets of the caller's tenant."""
    tickets = await list_tickets(db_session, tenant_id)
    logger.info("Listed {} tickets for tenant {}", len(tickets), tenant_id)
    return [TicketResponse.model_validate(ticket) for ticket in tickets]
