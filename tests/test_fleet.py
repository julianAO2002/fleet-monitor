"""Tests for the status rule and the fleet summary.

Nothing here waits. The rule takes the current time as a parameter, so a node
can be walked from ONLINE through STALE to OFFLINE in microseconds instead of
the ten minutes the thresholds describe. That is the reason the clock was
injected rather than read inside the function.

Two levels are covered on purpose: the rule in isolation, where the exact
boundaries can be pinned down, and the same rule through the HTTP API, which
proves it is actually wired up.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.config import Settings
from app.models import Node
from app.status import NodeStatus, compute_status

NOW = datetime(2026, 8, 17, 12, 0, 0, tzinfo=timezone.utc)


def _age_node(session: Session, name: str, silence: timedelta) -> None:
    """Backdate a node's last report, as if it had gone quiet."""
    node = session.exec(select(Node).where(Node.name == name)).one()
    node.last_seen_at = datetime.now(timezone.utc) - silence
    session.add(node)
    session.commit()


# ── The rule in isolation ───────────────────────────
@pytest.mark.parametrize(
    ("silence_s", "expected"),
    [
        (0, NodeStatus.ONLINE),
        (60, NodeStatus.ONLINE),
        # The boundaries, where an off-by-one would hide.
        (119, NodeStatus.ONLINE),
        (120, NodeStatus.ONLINE),
        (300, NodeStatus.STALE),
        (599, NodeStatus.STALE),
        (600, NodeStatus.OFFLINE),
        (86_400, NodeStatus.OFFLINE),
    ],
)
def test_status_follows_the_age_of_the_last_report(
    settings: Settings, silence_s: int, expected: NodeStatus
) -> None:
    last_seen = NOW - timedelta(seconds=silence_s)

    assert compute_status(last_seen, settings, NOW) == expected


def test_naive_timestamps_are_read_as_utc(settings: Settings) -> None:
    """Some drivers return timestamps without timezone information.

    Everything this system writes is UTC, so an unlabelled value is interpreted
    as such. Rejecting it would break reads that are perfectly valid.
    """
    naive = (NOW - timedelta(seconds=30)).replace(tzinfo=None)

    assert compute_status(naive, settings, NOW) == NodeStatus.ONLINE


def test_thresholds_come_from_configuration(settings: Settings) -> None:
    """An operator can widen the window for a route with poor coverage.

    Same silence, different verdict — because the threshold moved, not because
    the code changed.
    """
    patient = settings.model_copy(update={"stale_after_seconds": 600})
    last_seen = NOW - timedelta(seconds=300)

    assert compute_status(last_seen, settings, NOW) == NodeStatus.STALE
    assert compute_status(last_seen, patient, NOW) == NodeStatus.ONLINE


# ── The same rule through the API ───────────────────
def test_a_node_that_goes_quiet_becomes_stale(
    client: TestClient, session: Session, node_payload: dict[str, str]
) -> None:
    """Only last_seen_at is changed. Nothing writes a status anywhere."""
    client.post("/api/nodes", json=node_payload)

    _age_node(session, node_payload["name"], timedelta(minutes=5))

    assert client.get("/api/nodes").json()[0]["status"] == "STALE"


def test_a_node_that_stays_quiet_becomes_offline(
    client: TestClient, session: Session, node_payload: dict[str, str]
) -> None:
    client.post("/api/nodes", json=node_payload)

    _age_node(session, node_payload["name"], timedelta(minutes=30))

    assert client.get("/api/nodes").json()[0]["status"] == "OFFLINE"


def test_a_heartbeat_brings_a_node_back_online(
    client: TestClient,
    session: Session,
    node_payload: dict[str, str],
    heartbeat_payload: dict[str, float | int | str],
) -> None:
    """Recovery needs no intervention: the vessel simply reports again."""
    node_id = client.post("/api/nodes", json=node_payload).json()["id"]
    _age_node(session, node_payload["name"], timedelta(minutes=30))
    assert client.get(f"/api/nodes/{node_id}").json()["status"] == "OFFLINE"

    client.post(f"/api/nodes/{node_id}/heartbeats", json=heartbeat_payload)

    assert client.get(f"/api/nodes/{node_id}").json()["status"] == "ONLINE"


# ── Fleet summary ───────────────────────────────────
def test_fleet_status_of_an_empty_fleet(client: TestClient) -> None:
    body = client.get("/api/fleet/status").json()

    assert body == {"total": 0, "online": 0, "stale": 0, "offline": 0, "versions": {}}


def test_fleet_status_counts_each_state(
    client: TestClient, session: Session, node_payload: dict[str, str]
) -> None:
    """Three vessels, three states, derived from one column."""
    for name in ("vessel-01", "vessel-02", "vessel-03"):
        client.post("/api/nodes", json={**node_payload, "name": name})

    _age_node(session, "vessel-02", timedelta(minutes=5))
    _age_node(session, "vessel-03", timedelta(minutes=30))

    body = client.get("/api/fleet/status").json()

    assert body["total"] == 3
    assert body["online"] == 1
    assert body["stale"] == 1
    assert body["offline"] == 1


def test_fleet_status_exposes_a_partial_rollout(
    client: TestClient, node_payload: dict[str, str]
) -> None:
    """The operationally interesting number: who did not get the update."""
    client.post("/api/nodes", json={**node_payload, "name": "vessel-01"})
    client.post(
        "/api/nodes",
        json={**node_payload, "name": "vessel-02", "sw_version": "1.4.1"},
    )
    client.post("/api/nodes", json={**node_payload, "name": "vessel-03"})

    versions = client.get("/api/fleet/status").json()["versions"]

    assert versions == {"1.4.2": 2, "1.4.1": 1}
