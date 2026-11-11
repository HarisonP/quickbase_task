"""Database models: tenants, their tickets, and their chat conversations."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, CheckConstraint, DateTime, Enum, ForeignKey, String, Text, func
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


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


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


class Conversation(Base):
    """A chat conversation owned by one tenant. Its id is also the LangGraph thread_id."""

    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Message(Base):
    """A saved chat message: the user's message, the agent's final answer, or the agent's request
    for approval (no other tool traffic)."""

    __tablename__ = "messages"
    __table_args__ = (CheckConstraint(_in_values("role", MessageRole), name="ck_messages_role"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    role: Mapped[MessageRole] = mapped_column(_enum_column(MessageRole))
    content: Mapped[str] = mapped_column(Text)
    # Only on an approval request: the tool calls it asked about ({"tool", "args"} each), so the
    # client can show the approval again after a reload. Display only: what runs comes from the
    # agent's checkpoint.
    # none_as_null: no actions is SQL NULL, not the JSON value null.
    actions: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON(none_as_null=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
