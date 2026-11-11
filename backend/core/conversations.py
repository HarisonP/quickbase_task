"""Tenant-scoped conversation queries. Reads take the tenant, so another tenant's data is never returned."""

import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.models import Conversation, Message, MessageRole


async def create_conversation(db_session: AsyncSession, tenant_id: str) -> Conversation:
    conversation = Conversation(tenant_id=tenant_id)
    db_session.add(conversation)
    await db_session.commit()
    # Load created_at, which the database fills in.
    await db_session.refresh(conversation)
    return conversation


async def list_conversations(db_session: AsyncSession, tenant_id: str) -> list[Conversation]:
    statement = select(Conversation).where(Conversation.tenant_id == tenant_id).order_by(Conversation.created_at.desc())
    result = await db_session.scalars(statement)
    return list(result)


async def get_conversation(
    db_session: AsyncSession, tenant_id: str, conversation_id: uuid.UUID
) -> Conversation | None:
    """The conversation, or None if it doesn't exist *or* belongs to another tenant (indistinguishable)."""
    statement = select(Conversation).where(Conversation.id == conversation_id, Conversation.tenant_id == tenant_id)
    return await db_session.scalar(statement)


async def delete_conversation(db_session: AsyncSession, tenant_id: str, conversation_id: uuid.UUID) -> bool:
    """Delete the conversation and its messages (ON DELETE CASCADE). False if not the tenant's."""
    statement = (
        delete(Conversation)
        .where(Conversation.id == conversation_id, Conversation.tenant_id == tenant_id)
        .returning(Conversation.id)
    )
    deleted = await db_session.scalar(statement)

    await db_session.commit()
    return deleted is not None


async def list_messages(db_session: AsyncSession, tenant_id: str, conversation_id: uuid.UUID) -> list[Message]:
    statement = (
        select(Message)
        .join(Conversation)
        .where(Message.conversation_id == conversation_id, Conversation.tenant_id == tenant_id)
        # By time; id breaks ties between messages saved in the same instant.
        .order_by(Message.created_at, Message.id)
    )
    result = await db_session.scalars(statement)
    return list(result)


async def add_message(
    db_session: AsyncSession,
    conversation_id: uuid.UUID,
    role: MessageRole,
    content: str,
    actions: list[dict[str, Any]] | None = None,
) -> None:
    """Save a message. Only call it for a conversation already checked to belong to the caller.

    `actions`: only for an approval request, the tool calls it asks about.
    """
    db_session.add(Message(conversation_id=conversation_id, role=role, content=content, actions=actions))
    await db_session.commit()
