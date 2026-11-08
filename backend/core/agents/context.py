"""Per-run context passed to the agent by the server, never by the model."""

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentContext:
    # From the X-Tenant-ID header. Tools read it from here; the model cannot set it.
    tenant_id: str
