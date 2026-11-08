"""GET /api/tickets: the X-Tenant-ID header decides which tenant's tickets are returned.

The database queries are replaced with in-memory fakes, so no Postgres is needed.
"""

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from backend.api import dependencies
from backend.api import tickets as tickets_api
from backend.app.main import app
from backend.core.db import get_session
from backend.core.models import Ticket, TicketPriority, TicketStatus


def make_ticket(ticket_id: int, tenant_id: str, description: str) -> Ticket:
    return Ticket(
        id=ticket_id,
        tenant_id=tenant_id,
        title=f"Ticket {ticket_id}",
        description=description,
        status=TicketStatus.OPEN,
        priority=TicketPriority.LOW,
        created_at=datetime.now(UTC),
    )


TICKETS_BY_TENANT = {
    "acme": [make_ticket(1, "acme", "Login fails")],
    "globex": [make_ticket(47, "globex", "CONFIDENTIAL GLOBEX-SECRET-47")],
}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    async def fake_tenant_exists(db_session: object, tenant_id: str) -> bool:
        return tenant_id in TICKETS_BY_TENANT

    async def fake_list_tickets(db_session: object, tenant_id: str) -> list[Ticket]:
        return TICKETS_BY_TENANT[tenant_id]

    monkeypatch.setattr(dependencies, "tenant_exists", fake_tenant_exists)
    monkeypatch.setattr(tickets_api, "list_tickets", fake_list_tickets)
    app.dependency_overrides[get_session] = lambda: None
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_returns_only_the_header_tenants_tickets(client: TestClient) -> None:
    response = client.get("/api/tickets", headers={"X-Tenant-ID": "acme"})

    assert response.status_code == 200
    assert [ticket["id"] for ticket in response.json()] == [1]
    assert "GLOBEX-SECRET-47" not in response.text


def test_unknown_tenant_is_rejected(client: TestClient) -> None:
    response = client.get("/api/tickets", headers={"X-Tenant-ID": "nobody"})

    assert response.status_code == 401


def test_missing_tenant_header_is_rejected(client: TestClient) -> None:
    response = client.get("/api/tickets")

    assert response.status_code == 422
