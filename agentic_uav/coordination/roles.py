"""What a drone is doing for the team: its role, and what changes it (AUV-09, 9.1).

    keeper = RoleKeeper("Drone2", start=0.0)
    change = keeper.update(now, holding=net.holding, unreachable=detector.in_state(Health.UNREACHABLE))
    keeper.role, keeper.log

THE THREE ROLES:

    SCOUT     holds a task: searches it                      (holding a task)
    RELAY     positions itself to restore communication      (free, a teammate UNREACHABLE but not FAILED)
    RESERVE   stays available for a failed or returned task  (free, and nothing calls for a relay)

The role is a pure function of the drone's own belief -- what its contract-net
says it holds, and what its failure detector says of its teammates -- so it
follows from the agents' interactions and from nothing else (AUV-09, 9.4).

WHAT CHANGES IT (AUV-09 lists six things; how each is taken):

    remaining mission tasks     a task claimed makes a SCOUT; finished, a RESERVE
    loss of a teammate          its task comes back through the lease; a reserve bids, a SCOUT again
    communication topology      a teammate UNREACHABLE but not FAILED: a free drone bridges toward it (RELAY);
                                heard again (RECOVERED) or FAILED, the bridge is over
    battery                     a drone that can bid for nothing goes home (the policy's own checks)
    number of active drones     taken through the above: fewer drones, more returned tasks per reserve
    a high-priority target      not yet: no message carries a teammate's sighting (TARGET_FOUND has no
                                schema) -- the same reason RELAY's second trigger, "the base out of reach with
                                sightings unreported", waits for a later phase

PRIORITY: a task in hand outranks a relay, and a relay outranks waiting. A
SCOUT does not drop its task to relay; it may relay once it is free (9.3:
"a scout may become a relay if connectivity is lost").

UNDER PHASE 9's NETWORK every message is delivered, so an UNREACHABLE teammate
is a stopped one on its way to FAILED; a free drone may start to bridge toward
it for those twenty seconds, and stops when it is declared failed. Telling a
partition from a failure -- when the bridge would actually help -- is Phase 10's.

Every change is logged and announced (`ROLE_CHANGE`).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class Role(str, Enum):
    SCOUT = "scout"
    RELAY = "relay"
    RESERVE = "reserve"


def choose_role(holding: str | None, unreachable: tuple[str, ...]) -> tuple[Role, str]:
    """The role a drone's own belief calls for, and why."""
    if holding is not None:
        return Role.SCOUT, f"holds {holding}"
    if unreachable:
        return Role.RELAY, f"{', '.join(sorted(unreachable))} unreachable, not failed: bridge toward it"
    return Role.RESERVE, "holds no task: available for one returned"


def relay_point(base: tuple[float, float], last_known: tuple[float, float]) -> tuple[float, float]:
    """Where a relay holds: half way from the base to the silent teammate's last known position."""
    return ((base[0] + last_known[0]) / 2.0, (base[1] + last_known[1]) / 2.0)


@dataclass(frozen=True)
class RoleChange:
    at: float
    before: Role
    after: Role
    why: str

    def as_json(self) -> dict[str, Any]:
        return {"at": round(self.at, 3), "before": self.before.value, "after": self.after.value, "why": self.why}


class RoleKeeper:
    """One drone's role over the flight: it starts a RESERVE -- told the mission, holding nothing yet."""

    def __init__(self, owner: str, start: float) -> None:
        self.owner = owner
        self.role = Role.RESERVE
        self.since = start
        self.log: list[RoleChange] = []

    def update(self, now: float, holding: str | None, unreachable: tuple[str, ...]) -> RoleChange | None:
        role, why = choose_role(holding, unreachable)
        if role is self.role:
            return None
        change = RoleChange(now, self.role, role, why)
        self.role, self.since = role, now
        self.log.append(change)
        return change

    def as_json(self) -> dict[str, Any]:
        return {"owner": self.owner, "role": self.role.value, "log": [c.as_json() for c in self.log]}
