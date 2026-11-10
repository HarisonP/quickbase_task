"""The ticket fields the agent and the board are allowed to set."""

import pytest
from pydantic import ValidationError

from backend.core.models import TicketPriority, TicketStatus
from backend.core.tickets import NewTicket, TicketFields


@pytest.mark.parametrize("field", ["id", "tenant_id"])
def test_changes_cannot_touch_ownership(field: str) -> None:
    with pytest.raises(ValidationError):
        TicketFields.model_validate({field: "globex"})


@pytest.mark.parametrize(
    "changes",
    [{"title": ""}, {"title": "x" * 201}, {"status": "done"}, {"priority": "urgent"}],
)
def test_changes_reject_invalid_values(changes: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        TicketFields.model_validate(changes)


def test_changes_contain_only_what_was_set() -> None:
    fields = TicketFields(status=TicketStatus.CLOSED)

    assert fields.model_dump(exclude_none=True) == {"status": "closed"}


def test_new_ticket_is_open_and_medium_by_default() -> None:
    ticket = NewTicket(title="Printer jam", description="Tray 2 jams on every print.")

    assert ticket.status == TicketStatus.OPEN
    assert ticket.priority == TicketPriority.MEDIUM


def test_new_ticket_cannot_choose_its_tenant() -> None:
    with pytest.raises(ValidationError):
        NewTicket.model_validate({"title": "Printer jam", "description": "Tray 2 jams.", "tenant_id": "globex"})
