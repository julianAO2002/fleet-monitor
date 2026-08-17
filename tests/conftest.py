"""Shared test fixtures.

Every test runs against a SQLite database that lives in memory and is thrown
away afterwards, never against the development database. Two reasons: a suite
that writes into real data corrupts it, and a suite that leaves residue behind
passes the first time and fails the second.

Both the database session and the settings are substituted through FastAPI's
dependency overrides. No application module is modified or imported
differently — the handlers exercised here are byte-for-byte the ones that run
in production, which is the whole reason the session was injected rather than
imported.
"""

import os
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.config import Settings, get_settings
from app.database import get_session
from app.main import app

# Thresholds are pinned here rather than read from the environment, so the
# suite behaves identically on any machine and in CI. Deliberately small: the
# tests manipulate timestamps instead of waiting, but small numbers keep the
# arithmetic in each test easy to follow.
TEST_STALE_AFTER_S = 120
TEST_OFFLINE_AFTER_S = 600


@pytest.fixture(name="settings")
def settings_fixture() -> Settings:
    """Configuration with fixed thresholds.

    A real Settings instance, not a stand-in: it honours the same contract the
    application uses, so the code path under test is the real one.
    """
    return Settings(
        database_url="sqlite://",
        stale_after_seconds=TEST_STALE_AFTER_S,
        offline_after_seconds=TEST_OFFLINE_AFTER_S,
        environment="test",
    )


@pytest.fixture(name="session")
def session_fixture() -> Generator[Session, None, None]:
    """A database that exists only for the duration of one test.

    Defaults to SQLite in memory, which needs nothing installed and makes the
    suite fast enough to run constantly. Set ``TEST_DATABASE_URL`` to point the
    same tests at PostgreSQL — CI does this, so the suite runs twice: once for
    speed and once against the engine that actually ships. SQLite is forgiving
    in ways PostgreSQL is not, and a test that only ever sees SQLite cannot
    catch that.
    """
    database_url = os.getenv("TEST_DATABASE_URL", "sqlite://")

    if database_url.startswith("sqlite"):
        # SQLite creates a separate in-memory database per connection. Without
        # StaticPool the request would open a second, empty one and see none of
        # the rows the test just inserted.
        engine = create_engine(
            database_url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    else:
        engine = create_engine(database_url)

    # A real database persists between tests, so start each one from a known
    # empty schema rather than inheriting whatever the previous test left.
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        yield session

    SQLModel.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture(name="client")
def client_fixture(
    session: Session, settings: Settings
) -> Generator[TestClient, None, None]:
    """An HTTP client wired to the throwaway database.

    The two overrides are the entire adaptation needed to run the application
    against a different database and a different configuration. Nothing in
    ``app/`` is aware that it is being tested.
    """

    def get_session_override() -> Session:
        return session

    def get_settings_override() -> Settings:
        return settings

    app.dependency_overrides[get_session] = get_session_override
    app.dependency_overrides[get_settings] = get_settings_override

    yield TestClient(app)

    # Cleared so an override never leaks into the next test.
    app.dependency_overrides.clear()


@pytest.fixture(name="node_payload")
def node_payload_fixture() -> dict[str, str]:
    """A valid node registration body, for tests that need one node."""
    return {
        "name": "vessel-01",
        "vessel": "MV Atlantic Star",
        "location": "North Atlantic",
        "sw_version": "1.4.2",
    }


@pytest.fixture(name="heartbeat_payload")
def heartbeat_payload_fixture() -> dict[str, float | int | str]:
    """A valid heartbeat body."""
    return {
        "cpu_pct": 42.5,
        "disk_pct": 71.0,
        "uptime_s": 86400,
        "sw_version": "1.4.2",
    }
