"""Ticket routes, scoped to the caller's tenant."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from loguru import logger
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.dependencies import get_tenant_id
from backend.core.db import get_session
from backend.core.models import TicketPriority, TicketStatus
from backend.core.tickets import TicketFields, get_ticket, list_tickets, update_ticket

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


@router.patch("/{ticket_id}")
async def patch_ticket(
    ticket_id: int,
    body: TicketFields,
    tenant_id: str = Depends(get_tenant_id),
    db_session: AsyncSession = Depends(get_session),
) -> TicketResponse:
    """The user's own edit from the board (drag-and-drop, edit form): no approval step.

    Approval guards the agent's changes; this is the user acting directly.
    """
    changes = body.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Nothing to change.")

    # The tenant check is inside the UPDATE: another tenant's ticket matches no row.
    if not await update_ticket(db_session, tenant_id, ticket_id, changes):
        # Same answer for "doesn't exist" and "another tenant's".
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ticket not found")
    logger.info("Board updated ticket {} (tenant {}): {}", ticket_id, tenant_id, sorted(changes))

    ticket = await get_ticket(db_session, tenant_id, ticket_id)
    return TicketResponse.model_validate(ticket)
