"""Ticket routes, scoped to the caller's tenant."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from loguru import logger
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.dependencies import get_tenant_id
from backend.core.db import get_session
from backend.core.models import TicketPriority, TicketStatus
from backend.core.tickets import (
    NewTicket,
    TicketFields,
    create_ticket,
    delete_ticket,
    get_ticket,
    list_tickets,
    update_ticket,
)

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


@router.post("", status_code=status.HTTP_201_CREATED)
async def post_ticket(
    body: NewTicket,
    tenant_id: str = Depends(get_tenant_id),
    db_session: AsyncSession = Depends(get_session),
) -> TicketResponse:
    """A new ticket from the board, owned by the caller's tenant (taken from the header, never the body)."""
    ticket = await create_ticket(db_session, tenant_id, body)
    logger.info("Board created ticket {} (tenant {})", ticket.id, tenant_id)
    return TicketResponse.model_validate(ticket)


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


@router.delete("/{ticket_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_ticket(
    ticket_id: int,
    tenant_id: str = Depends(get_tenant_id),
    db_session: AsyncSession = Depends(get_session),
) -> None:
    """The user deletes a ticket from the board: no approval step, like the PATCH above."""
    # The tenant check is inside the DELETE: another tenant's ticket matches no row.
    if not await delete_ticket(db_session, tenant_id, ticket_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ticket not found")
    logger.info("Board deleted ticket {} (tenant {})", ticket_id, tenant_id)
