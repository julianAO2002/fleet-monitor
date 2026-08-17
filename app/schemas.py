"""API contracts: what each endpoint accepts and what it returns.

Kept separate from ``models.py`` because a table and an API contract are not
the same thing. A client creating a node supplies four fields; the server owns
``id``, ``created_at`` and ``last_seen_at``. A client reading a node gets those
back plus a ``status`` that exists in no column at all.

One schema per use case (Interface Segregation): a caller is never handed
fields it has no business seeing, and a new column does not leak through the
API until it is added here on purpose.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.status import NodeStatus


# ── Nodes ───────────────────────────────────────────
class NodeCreate(BaseModel):
    """Payload for registering a node.

    Server-owned fields are absent by design: a client cannot choose its own
    ``id`` or claim a ``created_at`` in the past.
    """

    name: str = Field(
        min_length=1,
        max_length=100,
        description="Unique identifier for the node, e.g. vessel-01",
        examples=["vessel-01"],
    )
    vessel: str = Field(min_length=1, max_length=100, examples=["MV Atlantic Star"])
    location: str = Field(min_length=1, max_length=100, examples=["North Atlantic"])
    sw_version: str = Field(min_length=1, max_length=50, examples=["1.4.2"])


class NodeRead(BaseModel):
    """A node as returned by the API, including its derived status."""

    # Allows building this schema straight from a SQLModel row.
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    vessel: str
    location: str
    sw_version: str
    created_at: datetime
    last_seen_at: datetime

    # Computed per request from last_seen_at; stored nowhere.
    status: NodeStatus


# ── Heartbeats ──────────────────────────────────────
class HeartbeatCreate(BaseModel):
    """Metrics reported by a node.

    Percentages are bounded so a malfunctioning agent reporting 400% CPU is
    rejected at the edge rather than stored and shown on a dashboard.
    """

    cpu_pct: float = Field(ge=0, le=100, examples=[42.5])
    disk_pct: float = Field(ge=0, le=100, examples=[71.0])
    uptime_s: int = Field(ge=0, examples=[86400])
    sw_version: str = Field(min_length=1, max_length=50, examples=["1.4.2"])


class HeartbeatRead(BaseModel):
    """A stored heartbeat as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    node_id: UUID
    cpu_pct: float
    disk_pct: float
    uptime_s: int
    sw_version: str
    created_at: datetime


# ── Fleet ───────────────────────────────────────────
class FleetStatus(BaseModel):
    """Aggregate view of the whole fleet.

    The question an operator actually asks: how many nodes are reachable, and
    what software is running out there.
    """

    total: int
    online: int
    stale: int
    offline: int

    # Version string -> number of nodes reporting it. Makes a partial rollout
    # visible at a glance: {"1.4.2": 180, "1.4.1": 20} means 20 nodes lagging.
    versions: dict[str, int]
