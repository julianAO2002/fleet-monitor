"""The rule that decides whether a node is reachable.

Status is derived, never stored. A node that sinks, loses power or drifts out
of satellite range stops reporting — and stops being able to tell anyone about
it. Any status written into a row would keep claiming ONLINE forever. Comparing
``last_seen_at`` against the clock cannot go stale, because it is recomputed on
every read.

    time since last_seen_at   <  stale_after    ->  ONLINE
                              <  offline_after  ->  STALE
                              >= offline_after  ->  OFFLINE
"""

from datetime import datetime, timezone
from enum import Enum

from app.config import Settings


class NodeStatus(str, Enum):
    """Reachability of a node, derived from the age of its last report.

    Inherits from ``str`` so it serialises to plain JSON ("ONLINE") rather than
    an object, while still being a closed set of values in Python: a typo like
    ``NodeStatus.ONLIN`` fails immediately instead of silently comparing false.
    """

    ONLINE = "ONLINE"
    STALE = "STALE"
    OFFLINE = "OFFLINE"


def compute_status(
    last_seen_at: datetime,
    settings: Settings,
    now: datetime | None = None,
) -> NodeStatus:
    """Return the status of a node given when it was last heard from.

    Args:
        last_seen_at: Timestamp of the node's most recent heartbeat.
        settings: Supplies the two thresholds, so operators can widen them for
            routes with poor coverage without the image being rebuilt.
        now: The moment to compare against. Injected rather than read from the
            clock inside this function, which lets tests walk a node through
            ONLINE, STALE and OFFLINE instantly instead of waiting ten minutes.

    Returns:
        The derived status.
    """
    now = now or datetime.now(timezone.utc)

    # Timestamps read back from a database column may arrive without tzinfo
    # depending on the driver. Everything this system writes is UTC, so an
    # unlabelled value is interpreted as such rather than rejected.
    if last_seen_at.tzinfo is None:
        last_seen_at = last_seen_at.replace(tzinfo=timezone.utc)

    silence_s = (now - last_seen_at).total_seconds()

    if silence_s < settings.stale_after_seconds:
        return NodeStatus.ONLINE
    if silence_s < settings.offline_after_seconds:
        return NodeStatus.STALE
    return NodeStatus.OFFLINE
