"""Application entry point.

Creates the FastAPI instance and mounts the routers. Adding a resource means
adding a router here, never editing an existing one (Open/Closed).
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, status
from sqlalchemy import text
from sqlmodel import Session

from app.config import Settings, get_settings
from app.database import get_session, init_db
from app.routers import fleet, nodes

_settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Prepare the schema before the application accepts traffic.

    Runs once at startup rather than on each request. A production system with
    an evolving schema would apply migrations here instead; see ``init_db``.
    """
    init_db()
    yield


app = FastAPI(
    title=_settings.app_name,
    description=(
        "Central API that tracks remote nodes through periodic heartbeats. "
        "Built for fleets with intermittent connectivity."
    ),
    version=_settings.app_version,
    lifespan=lifespan,
)

app.include_router(nodes.router)
app.include_router(fleet.router)


@app.get("/health", tags=["monitoring"])
def health(
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, str]:
    """Report whether the service can actually serve requests.

    Consumed by infrastructure rather than by users: the Dockerfile
    ``HEALTHCHECK`` polls it, and Compose relies on it for
    ``depends_on: condition: service_healthy``.

    The check queries the database instead of merely returning a constant. A
    process that is running but cannot reach its database is not healthy, and
    reporting 200 in that state would have Compose route traffic to a container
    that fails every request. Failure is 503, so the caller can distinguish
    "temporarily unable to serve" from a bug.
    """
    try:
        session.exec(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unreachable",
        ) from exc

    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "database": "connected",
    }
