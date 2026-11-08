"""Import the tenants and tickets from data/tickets.json into the database.

Rows whose id already exists are skipped, so running it again is harmless.
Run with: uv run poe import_tickets
"""

from pathlib import Path

from loguru import logger
from pydantic import BaseModel, ConfigDict
from sqlalchemy import create_engine, text
from sqlalchemy.dialects.postgresql import insert

from backend.core.config import get_database_url
from backend.core.models import Tenant, Ticket, TicketPriority, TicketStatus

TICKETS_FILE = Path(__file__).resolve().parents[2] / "data" / "tickets.json"


class TenantRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str


class TicketRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    tenant_id: str
    title: str
    description: str
    status: TicketStatus
    priority: TicketPriority


class TicketsFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenants: list[TenantRecord]
    tickets: list[TicketRecord]


def main() -> None:
    data = TicketsFile.model_validate_json(TICKETS_FILE.read_text())
    engine = create_engine(get_database_url())
    try:
        with engine.begin() as connection:
            # RETURNING yields only the rows actually inserted, i.e. not the skipped ones.
            tenants = connection.execute(
                insert(Tenant).on_conflict_do_nothing(index_elements=["id"]).returning(Tenant.id),
                [tenant.model_dump() for tenant in data.tenants],
            ).all()
            tickets = connection.execute(
                insert(Ticket).on_conflict_do_nothing(index_elements=["id"]).returning(Ticket.id),
                [ticket.model_dump() for ticket in data.tickets],
            ).all()
            # Ticket ids come from the file, so move the id sequence past them for tickets created later.
            connection.execute(
                text("SELECT setval(pg_get_serial_sequence('tickets', 'id'), (SELECT max(id) FROM tickets))")
            )
    finally:
        engine.dispose()
    logger.info("Imported {} new tenants and {} new tickets", len(tenants), len(tickets))


if __name__ == "__main__":
    main()
