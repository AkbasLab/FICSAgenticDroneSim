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


# --- Phase 17.3: the calibrated final profiles ---
#
# Chosen by scripts/calibrate_comms.py and written to
# configs/networks/final_profiles.yaml; frozen by Phase 17.4. Loaded here so a
# config can name `final_nominal`, `final_moderate` or `final_severe` exactly as
# it names the Phase 10 conditions. The Phase 10 conditions are kept unchanged
# so earlier results stay reproducible - but the calibration found the old
# `severe` unusable (its rate limit drops ~85% of messages in the stepped
# simulator, the same way every seed), so final experiments use these.

FINAL = []


def _load_final():
    import os
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "configs", "networks", "final_profiles.yaml")
    if not os.path.exists(path):
        return
    try:
        import yaml
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception:                                           # noqa: BLE001
        return
    for name, d in data.items():
        if not name.startswith("final_") or not isinstance(d, dict):
            continue
        _register(NetworkProfile(
            name=name,
            latency_ms_mean=float(d["latency_ms_mean"]),
            latency_ms_jitter=float(d["latency_ms_jitter"]),
            packet_loss_probability=float(d["packet_loss_probability"])))
        FINAL.append(name)


_load_final()


# --- Phase 18: the temporary partition, sized to the team ---
#
# The Phase 10 partition names Drone1-4, so it means nothing for a team of 2
# or 8. `final_partitioned` splits whichever team is flying into its first and
# second half for PARTITION_WINDOW_S, with the base on the first half's side,
# over the loss-free final link (so the partition is the only degradation).
# The window outlasts the presumed-lost threshold (4 x 8 s heartbeat) but ends
# before a typical mission does, so the halves must notice the split, carry on,
# and re-merge - which is what "temporary" is meant to test.

PARTITION_NAME = "final_partitioned"
PARTITION_WINDOW_S = (30.0, 150.0)


def partition_for(vehicle_ids, start_s=None, end_s=None):
    ids = list(vehicle_ids)
    half = max(1, len(ids) // 2)
    # The centralized controller sits at the base, so it is on the base side.
    # Without it in a group the partition would never touch drone<->controller
    # links and would have no effect at all on Architecture A (found by the
    # Phase 18 development run: A's partitioned cells equalled its nominal ones).
    from .fleet_controller import CONTROLLER_ID
    a, b = ids[:half] + [CONTROLLER_ID], ids[half:]
    base = CONDITIONS.get("final_nominal")
    start, end = PARTITION_WINDOW_S
    return NetworkProfile(
        name=PARTITION_NAME,
        latency_ms_mean=base.latency_ms_mean if base else 150.0,
        latency_ms_jitter=base.latency_ms_jitter if base else 50.0,
        packet_loss_probability=base.packet_loss_probability if base else 0.0,
        partitions=[Partition(group_a=a, group_b=b,
                              start_s=start if start_s is None else start_s,
                              end_s=end if end_s is None else end_s,
                              base_side="a")])


def resolve(name, vehicle_ids=None):
    """A condition by name, built for the team that is flying. Use this rather
    than `condition()` wherever the team is known."""
    if name == PARTITION_NAME:
        return partition_for(vehicle_ids or ["Drone1", "Drone2", "Drone3", "Drone4"])
    return condition(name)


# listed with the others, sized for the canonical 4-drone team
CONDITIONS[PARTITION_NAME] = partition_for(["Drone1", "Drone2", "Drone3", "Drone4"])


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
