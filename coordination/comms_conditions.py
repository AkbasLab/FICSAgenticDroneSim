"""The four communication conditions, and message lifetimes (Phase 10.2, 10.4).

**These numbers are experimental parameters, not claims about any real radio.**
They exist so two architectures can be compared under identical, reproducible
conditions. Calibrating them against a specific operational system would be a
separate piece of work.

Loading a condition by name gives every experiment the same definition:

    from agentic_uav.coordination.comms_conditions import condition
    profile = condition("severe")
"""

from .network_model import InterferenceZone, NetworkProfile, Partition
from .protocols import MessageType

# --- 10.2 the four conditions ---

CONDITIONS = {}


def _register(profile):
    CONDITIONS[profile.name] = profile
    return profile


NOMINAL = _register(NetworkProfile(
    name="nominal",
    latency_ms_mean=20.0,
    latency_ms_jitter=5.0,
    packet_loss_probability=0.0,
))

MODERATE = _register(NetworkProfile(
    name="moderate",
    latency_ms_mean=150.0,
    latency_ms_jitter=50.0,
    packet_loss_probability=0.10,
))

SEVERE = _register(NetworkProfile(
    name="severe",
    latency_ms_mean=600.0,
    latency_ms_jitter=250.0,
    packet_loss_probability=0.30,
    message_rate_limit=4.0,             # messages per second per sender
    burst_loss_probability=0.05,
    burst_length_s=3.0,
))


def partitioned(group_a=("Drone1", "Drone2"), group_b=("Drone3", "Drone4"),
                start_s=30.0, end_s=180.0, base_side="a"):
    """Two groups that cannot reach each other for a window.

    `base_side` says which group keeps contact with the base station; the other
    group is cut off from it as well as from their teammates.
    """
    return NetworkProfile(
        name="partitioned",
        latency_ms_mean=100.0,
        latency_ms_jitter=30.0,
        packet_loss_probability=0.05,
        partitions=[Partition(group_a=list(group_a), group_b=list(group_b),
                              start_s=start_s, end_s=end_s,
                              base_side=base_side)])


_register(partitioned())

ORDER = ["nominal", "moderate", "severe", "partitioned"]


def condition(name):
    """Look up a condition by name. Raises with the valid options if unknown."""
    if name not in CONDITIONS:
        raise KeyError(f"unknown condition {name!r}; "
                       f"expected one of {sorted(CONDITIONS)}")
    return CONDITIONS[name]


# --- 10.4 message lifetimes ---
#
# A delayed message can arrive after it has stopped being useful. A position
# from four heartbeat intervals ago is worse than nothing if it is treated as
# current, so short-lived traffic is allowed to expire in flight rather than be
# delivered stale. Mission constraints, by contrast, stay true all mission.

DEFAULT_TTL_S = 90.0

TTL_BY_TYPE = {
    # liveness and intent go stale almost immediately
    MessageType.HEARTBEAT: 90.0,
    MessageType.INTENT_UPDATE: 90.0,
    MessageType.STATUS_UPDATE: 180.0,

    # allocation traffic must outlive a skill, or a busy drone looks silent
    MessageType.TASK_ANNOUNCEMENT: 180.0,
    MessageType.TASK_BID: 180.0,
    MessageType.TASK_AWARD: 180.0,
    MessageType.TASK_ACCEPT: 180.0,
    MessageType.TASK_RELEASE: 180.0,
    MessageType.TASK_COMPLETE: 300.0,

    # findings stay useful for a long time - a target does not move
    MessageType.TARGET_FOUND: 600.0,
    MessageType.HELP_REQUEST: 120.0,
    MessageType.ROLE_CHANGE: 180.0,

    # mission-long
    MessageType.MISSION_UPDATE: float("inf"),
}


def ttl_for(message_type) -> float:
    return TTL_BY_TYPE.get(message_type, DEFAULT_TTL_S)


def summary():
    lines = []
    for name in ORDER:
        lines.append("  " + CONDITIONS[name].describe())
    return "\n".join(lines)
