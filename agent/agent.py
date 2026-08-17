"""Agent that simulates a node aboard a vessel.

Registers itself with the central API on startup, then reports metrics at a
fixed interval. Everything it needs comes from the environment, so the same
image runs as any vessel — which is what makes `--scale agent=3` produce three
distinct nodes rather than three copies of one.

The loop is deliberately tolerant of failure. A vessel loses connectivity as a
matter of course; an agent that exited on the first refused connection would
need a human to restart it, and there is nobody aboard to do that.
"""

import logging
import os
import random
import signal
import sys
import time
import uuid
from types import FrameType

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("agent")


class Config:
    """Agent configuration, read from the environment.

    Same discipline as the API: nothing hardcoded, so one image serves every
    vessel and thresholds can be tuned without a rebuild.
    """

    def __init__(self) -> None:
        self.api_url = os.getenv("API_URL", "http://api:8000").rstrip("/")

        # Falls back to a random suffix so `--scale agent=3` yields three
        # distinct names without three separate configurations.
        self.node_name = os.getenv("NODE_NAME") or f"vessel-{uuid.uuid4().hex[:6]}"

        self.vessel = os.getenv("VESSEL_NAME", "MV Unnamed")
        self.location = os.getenv("LOCATION", "Unknown waters")
        self.sw_version = os.getenv("SW_VERSION", "1.0.0")
        self.interval_s = int(os.getenv("HEARTBEAT_INTERVAL_SECONDS", "30"))
        self.timeout_s = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "10"))


class Agent:
    """Registers a node and reports on it until told to stop."""

    def __init__(self, config: Config, client: httpx.Client) -> None:
        self._config = config
        # Injected rather than constructed here, so the retry and reporting
        # logic can be exercised against a stub client.
        self._client = client
        self._node_id: str | None = None
        self._running = True

    def stop(self, signum: int, frame: FrameType | None) -> None:
        """Leave the reporting loop on SIGTERM so shutdown stays graceful."""
        log.info("signal %s received, shutting down", signum)
        self._running = False

    def register(self) -> str:
        """Register this node with the API, retrying until it answers.

        The agent may well start before the API is ready. Rather than exit and
        rely on a restart policy, it waits — the same thing it has to do when a
        satellite link drops mid-voyage.

        A 409 means this node is already known, which is the normal case for an
        agent that restarted. It recovers its id and carries on instead of
        treating its own history as an error.
        """
        payload = {
            "name": self._config.node_name,
            "vessel": self._config.vessel,
            "location": self._config.location,
            "sw_version": self._config.sw_version,
        }

        delay = 1.0
        while self._running:
            try:
                response = self._client.post(
                    f"{self._config.api_url}/api/nodes", json=payload
                )

                if response.status_code == 201:
                    node_id = response.json()["id"]
                    log.info("registered as %s (%s)", self._config.node_name, node_id)
                    return node_id

                if response.status_code == 409:
                    log.info("%s already registered, resuming", self._config.node_name)
                    return self._find_existing_id()

                log.warning("registration refused: %s %s", response.status_code, response.text)

            except httpx.HTTPError as exc:
                log.warning("API unreachable (%s), retrying in %.0fs", exc, delay)

            time.sleep(delay)
            # Back off gradually instead of hammering an API that is still
            # starting, but never wait so long that recovery is slow.
            delay = min(delay * 2, 30.0)

        raise SystemExit(0)

    def _find_existing_id(self) -> str:
        """Look up the id of an already-registered node by name."""
        response = self._client.get(f"{self._config.api_url}/api/nodes")
        response.raise_for_status()
        for node in response.json():
            if node["name"] == self._config.node_name:
                return node["id"]
        raise RuntimeError(f"{self._config.node_name} reported as taken but not listed")

    def _collect_metrics(self) -> dict[str, float | int | str]:
        """Produce a metrics sample.

        Synthetic here. A real agent would read the host: /proc/stat for CPU,
        statvfs for disk, /proc/uptime. The API contract is identical either
        way, which is the point — the central side does not care where the
        numbers came from.
        """
        return {
            "cpu_pct": round(random.uniform(5, 85), 1),
            "disk_pct": round(random.uniform(30, 90), 1),
            "uptime_s": int(time.monotonic()),
            "sw_version": self._config.sw_version,
        }

    def send_heartbeat(self) -> bool:
        """Send one report. Returns whether it was accepted."""
        try:
            response = self._client.post(
                f"{self._config.api_url}/api/nodes/{self._node_id}/heartbeats",
                json=self._collect_metrics(),
            )
            if response.status_code == 201:
                body = response.json()
                log.info(
                    "heartbeat sent  cpu=%.1f%%  disk=%.1f%%",
                    body["cpu_pct"],
                    body["disk_pct"],
                )
                return True

            # The central database may have been reset while this agent kept
            # running. Re-register rather than report into a void forever.
            if response.status_code == 404:
                log.warning("node no longer known to the API, re-registering")
                self._node_id = self.register()
                return False

            log.warning("heartbeat rejected: %s %s", response.status_code, response.text)
            return False

        except httpx.HTTPError as exc:
            # Expected, not exceptional: this is what a dropped link looks like.
            # The API will move this node to STALE and then OFFLINE on its own.
            log.warning("heartbeat failed (%s), will retry", exc)
            return False

    def run(self) -> None:
        """Register, then report until stopped."""
        log.info(
            "starting  node=%s  vessel=%s  api=%s  interval=%ss",
            self._config.node_name,
            self._config.vessel,
            self._config.api_url,
            self._config.interval_s,
        )

        self._node_id = self.register()

        while self._running:
            self.send_heartbeat()

            # Sleep in short slices so SIGTERM is noticed promptly instead of
            # after the full interval.
            for _ in range(self._config.interval_s):
                if not self._running:
                    break
                time.sleep(1)

        log.info("stopped")


def main() -> int:
    config = Config()

    with httpx.Client(timeout=config.timeout_s) as client:
        agent = Agent(config, client)

        # Without this, `docker stop` waits ten seconds and then kills the
        # process; with it, the agent exits as soon as it is asked to.
        signal.signal(signal.SIGTERM, agent.stop)
        signal.signal(signal.SIGINT, agent.stop)

        agent.run()

    return 0


if __name__ == "__main__":
    sys.exit(main())
