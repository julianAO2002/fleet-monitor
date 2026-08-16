"""Database tables.

Two entities: a ``Node`` is a remote machine aboard a vessel, and a
``Heartbeat`` is one report that node sent. One node has many heartbeats.

Note what is absent: there is no ``status`` column. A node's status is derived
from ``last_seen_at`` at query time rather than stored, because a stored status
goes stale on its own — when a vessel loses connectivity there is nobody left
to write "OFFLINE" into the row. See ``app/status.py``.
"""

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlmodel import Field, Relationship, SQLModel


def utcnow() -> datetime:
    """Return the current time as a timezone-aware UTC value.

    Every timestamp in this system is UTC. Vessels are spread across time
    zones, so a naive local time would make two reports impossible to compare.
    """
    return datetime.now(timezone.utc)


class Node(SQLModel, table=True):
    """A remote machine that reports to the fleet monitor."""

    id: UUID = Field(default_factory=uuid4, primary_key=True)

    # Unique at the database level rather than checked in application code:
    # the constraint holds even if two requests race each other.
    name: str = Field(unique=True, index=True, max_length=100)

    vessel: str = Field(max_length=100)
    location: str = Field(max_length=100)

    # Software version currently reported by the node. Updated on every
    # heartbeat, which is how the fleet summary knows what is deployed where.
    sw_version: str = Field(max_length=50)

    created_at: datetime = Field(default_factory=utcnow)

    # The single field the status rule depends on. Refreshed on each heartbeat.
    last_seen_at: datetime = Field(default_factory=utcnow, index=True)

    heartbeats: list["Heartbeat"] = Relationship(
        back_populates="node",
        # Deleting a node removes its heartbeats instead of leaving rows that
        # point at nothing.
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class Heartbeat(SQLModel, table=True):
    """One metrics report sent by a node."""

    id: UUID = Field(default_factory=uuid4, primary_key=True)

    # Enforced by the database: a heartbeat cannot reference a node that does
    # not exist.
    node_id: UUID = Field(foreign_key="node.id", index=True)

    cpu_pct: float
    disk_pct: float
    uptime_s: int

    # Carried on every heartbeat rather than read from the node record, so the
    # report stays truthful even if the node was upgraded between beats.
    sw_version: str = Field(max_length=50)

    created_at: datetime = Field(default_factory=utcnow, index=True)

    node: Node | None = Relationship(back_populates="heartbeats")
