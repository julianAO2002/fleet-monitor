"""Aggregate view of the fleet.

Separate from ``nodes.py`` because it answers a different question: not "what
is this node doing" but "what is the state of everything out there". Adding it
required mounting a new router, not editing an existing one (Open/Closed).
"""

from collections import Counter
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.config import Settings, get_settings
from app.database import get_session
from app.models import Node
from app.schemas import FleetStatus
from app.status import NodeStatus, compute_status

router = APIRouter(prefix="/api/fleet", tags=["fleet"])


@router.get("/status", response_model=FleetStatus)
def fleet_status(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> FleetStatus:
    """Summarise how many nodes are reachable and what they are running.

    Every node is evaluated against a single ``now`` captured once, so the
    counts describe one consistent instant. Reading the clock per node would
    let a slow query classify the first and last node against different times.

    The version tally is the operationally interesting part: it exposes a
    partial rollout at a glance. ``{"1.4.2": 180, "1.4.1": 20}`` means twenty
    vessels never received the update.
    """
    now = datetime.now(timezone.utc)
    nodes = session.exec(select(Node)).all()

    statuses = Counter(
        compute_status(node.last_seen_at, settings, now) for node in nodes
    )
    versions = Counter(node.sw_version for node in nodes)

    return FleetStatus(
        total=len(nodes),
        online=statuses[NodeStatus.ONLINE],
        stale=statuses[NodeStatus.STALE],
        offline=statuses[NodeStatus.OFFLINE],
        versions=dict(versions),
    )
