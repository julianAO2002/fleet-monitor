"""Tests for node registration and heartbeat reporting.

Each test verifies one behaviour, so a failure names the broken thing without
anyone having to read the body. None of them knows which database is in use:
they ask for a client and the fixtures do the rest.
"""

from uuid import uuid4

from fastapi.testclient import TestClient

UNKNOWN_ID = uuid4()


# ── Registration ────────────────────────────────────
def test_create_node_returns_201_and_the_stored_node(
    client: TestClient, node_payload: dict[str, str]
) -> None:
    response = client.post("/api/nodes", json=node_payload)

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == node_payload["name"]
    assert body["vessel"] == node_payload["vessel"]


def test_create_node_assigns_a_server_side_id(
    client: TestClient, node_payload: dict[str, str]
) -> None:
    """The client supplies four fields; the server owns the identity."""
    response = client.post("/api/nodes", json=node_payload)

    body = response.json()
    assert body["id"]
    assert body["created_at"]
    assert body["last_seen_at"]


def test_a_freshly_created_node_is_online(
    client: TestClient, node_payload: dict[str, str]
) -> None:
    """Registration sets last_seen_at, so the node starts reachable."""
    response = client.post("/api/nodes", json=node_payload)

    assert response.json()["status"] == "ONLINE"


def test_duplicate_name_is_rejected_as_conflict(
    client: TestClient, node_payload: dict[str, str]
) -> None:
    """409 rather than 500: the request is invalid, the server is fine.

    The uniqueness is enforced by the database constraint, not by a prior
    SELECT that two concurrent requests could both pass.
    """
    client.post("/api/nodes", json=node_payload)

    response = client.post("/api/nodes", json=node_payload)

    assert response.status_code == 409
    assert node_payload["name"] in response.json()["detail"]


def test_empty_name_is_rejected_before_reaching_the_database(
    client: TestClient, node_payload: dict[str, str]
) -> None:
    response = client.post("/api/nodes", json={**node_payload, "name": ""})

    assert response.status_code == 422


def test_missing_field_is_rejected(client: TestClient) -> None:
    response = client.post("/api/nodes", json={"name": "vessel-01"})

    assert response.status_code == 422


# ── Reading ─────────────────────────────────────────
def test_list_nodes_is_empty_before_anything_is_registered(client: TestClient) -> None:
    response = client.get("/api/nodes")

    assert response.status_code == 200
    assert response.json() == []


def test_list_nodes_returns_every_registered_node(
    client: TestClient, node_payload: dict[str, str]
) -> None:
    client.post("/api/nodes", json=node_payload)
    client.post("/api/nodes", json={**node_payload, "name": "vessel-02"})

    response = client.get("/api/nodes")

    assert len(response.json()) == 2


def test_get_unknown_node_returns_404(client: TestClient) -> None:
    response = client.get(f"/api/nodes/{UNKNOWN_ID}")

    assert response.status_code == 404


# ── Heartbeats ──────────────────────────────────────
def test_heartbeat_is_recorded(
    client: TestClient,
    node_payload: dict[str, str],
    heartbeat_payload: dict[str, float | int | str],
) -> None:
    node_id = client.post("/api/nodes", json=node_payload).json()["id"]

    response = client.post(f"/api/nodes/{node_id}/heartbeats", json=heartbeat_payload)

    assert response.status_code == 201
    assert response.json()["node_id"] == node_id


def test_heartbeat_updates_the_node_reported_version(
    client: TestClient,
    node_payload: dict[str, str],
    heartbeat_payload: dict[str, float | int | str],
) -> None:
    """A node that reports a new version is now running it.

    This is what makes the fleet version tally reflect reality rather than
    whatever was true at registration.
    """
    node_id = client.post("/api/nodes", json=node_payload).json()["id"]

    client.post(
        f"/api/nodes/{node_id}/heartbeats",
        json={**heartbeat_payload, "sw_version": "1.5.0"},
    )

    assert client.get(f"/api/nodes/{node_id}").json()["sw_version"] == "1.5.0"


def test_heartbeat_for_unknown_node_returns_404(
    client: TestClient, heartbeat_payload: dict[str, float | int | str]
) -> None:
    response = client.post(
        f"/api/nodes/{UNKNOWN_ID}/heartbeats", json=heartbeat_payload
    )

    assert response.status_code == 404


def test_impossible_cpu_reading_is_rejected(
    client: TestClient,
    node_payload: dict[str, str],
    heartbeat_payload: dict[str, float | int | str],
) -> None:
    """A malfunctioning agent is stopped at the edge, not stored and charted."""
    node_id = client.post("/api/nodes", json=node_payload).json()["id"]

    response = client.post(
        f"/api/nodes/{node_id}/heartbeats",
        json={**heartbeat_payload, "cpu_pct": 400},
    )

    assert response.status_code == 422


def test_heartbeats_are_listed_newest_first(
    client: TestClient,
    node_payload: dict[str, str],
    heartbeat_payload: dict[str, float | int | str],
) -> None:
    node_id = client.post("/api/nodes", json=node_payload).json()["id"]
    for version in ("1.0.0", "1.1.0", "1.2.0"):
        client.post(
            f"/api/nodes/{node_id}/heartbeats",
            json={**heartbeat_payload, "sw_version": version},
        )

    body = client.get(f"/api/nodes/{node_id}/heartbeats").json()

    assert len(body) == 3
    assert [h["created_at"] for h in body] == sorted(
        (h["created_at"] for h in body), reverse=True
    )


def test_heartbeat_listing_respects_the_limit(
    client: TestClient,
    node_payload: dict[str, str],
    heartbeat_payload: dict[str, float | int | str],
) -> None:
    """The table grows without end, so the endpoint is bounded."""
    node_id = client.post("/api/nodes", json=node_payload).json()["id"]
    for _ in range(5):
        client.post(f"/api/nodes/{node_id}/heartbeats", json=heartbeat_payload)

    response = client.get(f"/api/nodes/{node_id}/heartbeats?limit=2")

    assert len(response.json()) == 2


# ── Health ──────────────────────────────────────────
def test_health_reports_the_database_is_reachable(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["database"] == "connected"
