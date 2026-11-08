"""FastAPI dependencies shared by the routers."""

from fastapi import Depends, Header, HTTPException, Request, status
from langgraph.graph.state import CompiledStateGraph
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.db import get_session
from backend.core.tickets import tenant_exists


async def get_tenant_id(x_tenant_id: str = Header(), db_session: AsyncSession = Depends(get_session)) -> str:
    """Stand-in for real auth: the X-Tenant-ID header names the caller's tenant."""
    if not await tenant_exists(db_session, x_tenant_id):
        logger.warning("Rejected request for unknown tenant {!r}", x_tenant_id)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown tenant")
    return x_tenant_id


def get_agent(request: Request) -> CompiledStateGraph:
    agent: CompiledStateGraph = request.app.state.agent
    return agent
