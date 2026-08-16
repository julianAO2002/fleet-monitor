"""Application entry point.

Creates the FastAPI instance and exposes the liveness endpoint. Routers for
nodes and fleet are mounted here as they are added, so growing the API never
requires editing an existing router (Open/Closed).
"""

from typing import Annotated

from fastapi import Depends, FastAPI

from app.config import Settings, get_settings

app = FastAPI(
    title="fleet-monitor",
    description=(
        "Central API that tracks remote nodes through periodic heartbeats. "
        "Built for fleets with intermittent connectivity."
    ),
    version="0.1.0",
)


@app.get("/health", tags=["monitoring"])
def health(settings: Annotated[Settings, Depends(get_settings)]) -> dict[str, str]:
    """Report that the service is alive.

    Consumed by infrastructure rather than by users: the Dockerfile
    ``HEALTHCHECK`` polls it, and Compose relies on it for
    ``depends_on: condition: service_healthy``. Database connectivity is added
    to this check on day 2, once the engine exists.

    The settings object arrives injected instead of imported, so the handler
    depends on an abstraction it can be given, not on a global it must find.
    """
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
    }
