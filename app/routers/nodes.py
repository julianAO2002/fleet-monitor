"""Endpoints for registering nodes and receiving their heartbeats.

Handlers translate HTTP to and from the domain and nothing else: they receive
input already validated by the schemas, delegate the status decision to
``compute_status``, and return. No threshold or business rule is written here,
so changing the rule means touching ``status.py`` alone.

Both the database session and the settings arrive injected, never imported.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status as http_status
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, desc, select

from app.config import Settings, get_settings
from app.database import get_session
from app.models import Heartbeat, Node, utcnow
from app.schemas import HeartbeatCreate, HeartbeatRead, NodeCreate, NodeRead
from app.status import compute_status

router = APIRouter(prefix="/api/nodes", tags=["nodes"])

SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def _to_read(node: Node, settings: Settings) -> NodeRead:
    """Attach the derived status to a node row on its way out."""
    return NodeRead(
        **node.model_dump(),
        status=compute_status(node.last_seen_at, settings),
    )


def _get_or_404(node_id: UUID, session: Session) -> Node:
    """Load a node or fail the request with 404."""
    node = session.get(Node, node_id)
    if node is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=f"Node {node_id} not found",
        )
    return node


@router.post("", response_model=NodeRead, status_code=http_status.HTTP_201_CREATED)
def create_node(
    payload: NodeCreate,
    session: SessionDep,
    settings: SettingsDep,
) -> NodeRead:
    """Register a new node.

    A duplicate name is rejected with 409, not 500: the request is invalid, the
    server is fine. The unique constraint is enforced by the database rather
    than by a prior SELECT, which would leave a window for two concurrent
    requests to both pass the check.
    """
    node = Node(**payload.model_dump())
    session.add(node)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=f"A node named '{payload.name}' already exists",
        ) from exc

    session.refresh(node)
    return _to_read(node, settings)


@router.get("", response_model=list[NodeRead])
def list_nodes(session: SessionDep, settings: SettingsDep) -> list[NodeRead]:
    """List every node with its status computed at this instant."""
    nodes = session.exec(select(Node).order_by(Node.name)).all()
    return [_to_read(node, settings) for node in nodes]


@router.get("/{node_id}", response_model=NodeRead)
def get_node(node_id: UUID, session: SessionDep, settings: SettingsDep) -> NodeRead:
    """Return a single node."""
    return _to_read(_get_or_404(node_id, session), settings)


@router.post(
    "/{node_id}/heartbeats",
    response_model=HeartbeatRead,
    status_code=http_status.HTTP_201_CREATED,
)
def create_heartbeat(
    node_id: UUID,
    payload: HeartbeatCreate,
    session: SessionDep,
) -> HeartbeatRead:
    """Record a heartbeat and refresh the node's liveness.

    Two writes in one transaction: the heartbeat is appended to the history,
    and the node's ``last_seen_at`` and ``sw_version`` are updated. The first
    is the audit trail; the second is what moves the node back to ONLINE and
    reports which version it is now running.
    """
    node = _get_or_404(node_id, session)

    heartbeat = Heartbeat(node_id=node.id, **payload.model_dump())
    session.add(heartbeat)

    node.last_seen_at = utcnow()
    node.sw_version = payload.sw_version
    session.add(node)

    session.commit()
    session.refresh(heartbeat)
    return HeartbeatRead.model_validate(heartbeat)


@router.get("/{node_id}/heartbeats", response_model=list[HeartbeatRead])
def list_heartbeats(
    node_id: UUID,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> list[HeartbeatRead]:
    """Return the most recent heartbeats for a node, newest first.

    Bounded by ``limit`` because this table grows without end: three agents
    reporting every 30 seconds add roughly a quarter of a million rows a month.
    An unbounded query would eventually try to serialise all of them.
    """
    _get_or_404(node_id, session)

    rows = session.exec(
        select(Heartbeat)
        .where(Heartbeat.node_id == node_id)
        .order_by(desc(Heartbeat.created_at))
        .limit(limit)
    ).all()
    return [HeartbeatRead.model_validate(row) for row in rows]
