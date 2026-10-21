"""The plan language: eight actions, the JSON schema the model must follow, and
the validation a schema cannot express.

Shared by every planner, so a plan means the same thing whoever produced it.

Moved verbatim from `baseline/open_loop_agent.py` in Phase 2 step 4;
`tests/test_golden.py` proves every planning request and record is unchanged.
"""

from __future__ import annotations

from typing import Any

from ..core.errors import PlanError
from ..core.protocol import CRUISE_ALTITUDE

MAX_DURATION = 60.0      # seconds; a single leg longer than this is rejected
MAX_ALTITUDE = -120.0    # metres NED; roughly the legal ceiling for small UAS
MIN_ALTITUDE = -2.0      # metres NED; below this is effectively ground level


ACTIONS = (
    "fly_to", "fly_straight", "fly_backward", "fly_left", "fly_right",
    "hover", "set_altitude", "land",
)

# The schema is the single most important part of this agent. Small local models
# collapse multi-step requests into one action when left unconstrained -- asked
# to hover then land, they return only the hover. Requiring an array, and
# restricting the action name to an enum, fixes that and also stops the model
# inventing actions that do not exist.
PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "plan": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": list(ACTIONS)},
                    "duration": {"type": "number"},
                    "x": {"type": "number"},
                    "y": {"type": "number"},
                    "z": {"type": "number"},
                },
                "required": ["action"],
            },
        }
    },
    "required": ["plan"],
}


def validate(plan: Any) -> tuple[list[dict[str, Any]], list[str]]:
    """Check a plan is flyable. Returns (steps, notes) or raises PlanError.

    The schema already guarantees shape and action names. This checks the things
    a schema cannot: that parameters are present for the action that needs them,
    that durations are sane, and that altitudes are the right sign.
    """
    if not isinstance(plan, dict) or "plan" not in plan:
        raise PlanError("no 'plan' key in model output")
    steps = plan["plan"]
    if not isinstance(steps, list) or not steps:
        raise PlanError("'plan' is not a non-empty array")

    notes: list[str] = []
    checked: list[dict[str, Any]] = []

    for position, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            raise PlanError(f"step {position} is not an object")
        action = step.get("action")
        if action not in ACTIONS:
            raise PlanError(f"step {position}: unknown action {action!r}")

        if action in ("fly_straight", "fly_backward", "fly_left", "fly_right", "hover"):
            duration = step.get("duration")
            if not isinstance(duration, (int, float)):
                raise PlanError(f"step {position}: {action} needs a duration")
            if duration <= 0:
                raise PlanError(f"step {position}: duration must be positive")
            if duration > MAX_DURATION:
                raise PlanError(
                    f"step {position}: duration {duration}s exceeds the {MAX_DURATION}s limit"
                )

        if action == "set_altitude":
            z = step.get("z")
            if not isinstance(z, (int, float)):
                raise PlanError(f"step {position}: set_altitude needs z")
            if z > 0:
                # The model meant "up". Obeying the sign would fly into the
                # ground, so normalise and record that it happened -- silently
                # correcting a model error would hide a real failure mode.
                notes.append(f"step {position}: z={z} treated as {-z} (NED, negative is up)")
                z = -float(z)
            if z > MIN_ALTITUDE:
                raise PlanError(f"step {position}: z={z} is at or below ground level")
            if z < MAX_ALTITUDE:
                raise PlanError(f"step {position}: z={z} exceeds the {MAX_ALTITUDE}m ceiling")
            step = dict(step, z=float(z))

        if action == "fly_to":
            for axis in ("x", "y"):
                if not isinstance(step.get(axis), (int, float)):
                    raise PlanError(f"step {position}: fly_to needs {axis}")
            z = step.get("z", CRUISE_ALTITUDE)
            if not isinstance(z, (int, float)):
                raise PlanError(f"step {position}: fly_to z must be a number")
            if z > 0:
                notes.append(f"step {position}: z={z} treated as {-z} (NED, negative is up)")
                z = -float(z)
            # NOT bounds-checked, unlike set_altitude. The asymmetry is real
            # and the behaviour is DELIBERATE as of 2026-10-19: left alone, so
            # "return home" means the origin at ground level and M04 scores as
            # the model wrote it. set_altitude refuses z = 0 as "at or below
            # ground level"; fly_to accepts it, and since altitudes are anchored
            # to the measured ground, z = 0 means the terrain. Measured
            # 2026-10-09: two drones told to "return home and land" from 70 m and
            # 55 m both arrived at 0.04 m AGL after fly_to, where its default
            # implies 8 m. It explains M04 finishing at 0.27 m where every other
            # mission finishes near 1.17 m.
            #
            # Applying the bounds here was tried and REVERTED on 2026-10-09:
            # the model emits {"x":0,"y":0,"z":0} for M04 in all three attempts,
            # so the bounds turn a 3/3 mission into 0/3. Decided 2026-10-19 to
            # leave it: nothing in the prompt tells the model fly_to's z has a
            # floor, so rejecting the plan would score it against a rule it was
            # never given. The consequence is recorded instead -- a fly_to with
            # z = 0 arrives at ground level, which is why M04 finishes at 0.27 m
            # where other missions finish near 1.17 m. See the phase log.
            step = dict(step, z=float(z))

        checked.append(step)

    return checked, notes
