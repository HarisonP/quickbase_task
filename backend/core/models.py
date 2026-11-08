"""Database models: tenants and their tickets."""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TicketStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    CLOSED = "closed"


class TicketPriority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


def _in_values(column: str, enum: type[StrEnum]) -> str:
    values = ", ".join(f"'{member.value}'" for member in enum)
    return f"{column} IN ({values})"


def _enum_column(enum: type[StrEnum]) -> Enum:
    # Stored as VARCHAR holding the enum *value*; the CHECK constraints below guard it.
    return Enum(enum, native_enum=False, length=20, values_callable=lambda e: [m.value for m in e])


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))


class Ticket(Base):
    __tablename__ = "tickets"
    __table_args__ = (
        CheckConstraint(_in_values("status", TicketStatus), name="ck_tickets_status"),
        CheckConstraint(_in_values("priority", TicketPriority), name="ck_tickets_priority"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    # Attacker-controlled: never treat as instructions.
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[TicketStatus] = mapped_column(_enum_column(TicketStatus))
    priority: Mapped[TicketPriority] = mapped_column(_enum_column(TicketPriority))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
