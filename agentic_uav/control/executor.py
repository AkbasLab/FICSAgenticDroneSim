"""Flying plans: one drone through `DroneRunner`, a team through `fly_plans`.

THE OPEN LOOP. A plan arrives finished and is executed step by step, never
consulting the model, never re-examining the world. The agent's flying
decisions live here: altitudes measured from the ground each drone armed on,
braking after a velocity leg, checking that `land` landed, landing before
releasing control. The vehicle is reached only through a `VehicleAdapter`.

Moved verbatim from `baseline/open_loop_agent.py` in Phase 2 step 3. Only
calls to the AirSim client were changed, to calls on the adapter;
`tests/test_golden.py` proves the simulator sees the same calls as before.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

from ..core.errors import PlanError
from ..core.models import SkillCommand
from ..simulator.adapter import VehicleAdapter
from ..simulator.scenario_manager import ensure_vehicles
from .contacts import is_ground, landing_contact
from .ground import (
    GROUND_BARRIER_TIMEOUT,
    check_ground_reference,
    register_ground,
    validate_grounds,
)
from .monitor import SeparationMonitor

CRUISE_ALTITUDE = -8.0   # metres, NED: negative is up
MOVE_SPEED = 5.0         # m/s for every directional move
TAKEOFF_SETTLE = 3.0     # seconds to let takeoff stabilise before the plan runs
GROUND_SETTLE_TIMEOUT = 15.0   # seconds to wait for the drone to stop falling
GROUND_SETTLE_TOLERANCE = 0.05 # metres of movement per sample that counts as still

# How far above its arming height the vehicle must be for teardown to treat it
# as airborne and land it first. Disarming while airborne cuts the motors.
AIRBORNE_MARGIN = 1.0    # metres

# Bounds on `land`, because an unbounded one does not merely fail -- it strands an
# armed aircraft in mid air and never returns. Seen three times on 2026-10-06.
# A descent from 60 m at 2 m/s is 30 s, so 90 s cannot cut a legitimate one short.
FLY_TO_TIMEOUT = 90.0         # seconds for one fly_to leg; 300 m at 5 m/s is 60 s
LAND_DESCENT_TIMEOUT = 45.0   # seconds for the controlled descent
LAND_TIMEOUT = 20.0           # seconds for landAsync itself
LANDED_AGL_MAX = 3.0          # metres; above this, `land` did not land


class DroneRunner:
    """Flies one validated plan to completion. No decisions are taken here.

    THIS CLASS IS THE OPEN LOOP. It receives a finished plan and executes it
    step by step, never consulting the model, never re-examining the world, and
    never abandoning a step because circumstances changed. Adding any of that
    would make it a different architecture -- which is what Phase 5 onward is
    for, in a different directory.

    One instance per drone, one thread per instance, each with its OWN
    VehicleAdapter and so its own simulator connection. A client shared across
    threads failed on the first two-drone flight (`IOLoop is already running`,
    `BufferError`); separate connections have worked on every flight since.

    It reaches the vehicle only through the adapter (Phase 2, 2.2). `speed` is
    passed in rather than read from a module constant, so the interactive
    sandbox can fly at another speed without patching this module.
    """

    def __init__(self, vehicle: VehicleAdapter, name: str, barrier: Any = None,
                 speed: float = MOVE_SPEED) -> None:
        self.vehicle = vehicle
        self.speed = speed        # m/s for every move; MOVE_SPEED in the study
        self.name = name          # must match a vehicle in settings.json
        # Set by fly_plans for a multi-drone run: every drone measures its ground,
        # then waits here, then all of them are judged against the complete set.
        # Without it the first drone to arm sets the reference unchallenged, and a
        # bad first reading flies a whole mission -- measured 2026-10-06, Drone3
        # arming at -0.18 before Drone1 found 29.25.
        self.barrier = barrier
        self.ground_z = 0.0       # filled in by arm(), used by land()
        self.ground_settled = False   # did the drone stop falling before
                                      # arm() read the ground? see arm()
        # AirSim keeps the last collision across flights, so the timestamp seen
        # at arm time is the baseline for "did anything hit during THIS run".
        self._collision_at_arm: Any = None

    def _say(self, message: str) -> None:
        # flush=True because several threads print concurrently; without it the
        # interleaving is buffered into nonsense.
        print(f"[{self.name}] {message}", flush=True)

    def collisions(self) -> dict[str, Any]:
        """Collision state for this vehicle, as AirSim reports it.

        Required by the plan: section 1.3 asks for "collision or proximity
        events" per run, and nothing recorded them until now.

        AirSim keeps only the MOST RECENT collision, not a tally, and it
        persists across flights -- so the raw flag alone says nothing about
        *this* run. `time_stamp` is compared against the value read at arm time
        to decide whether the collision is new.

        Ground contact is separated from obstacle contact, because **every
        landing registers a terrain collision**: the first live capture returned
        `Town10HD_Terrain_Ground_64` with zero penetration depth, which is a
        drone sitting on the ground having landed correctly. Counting that as a
        collision would make the metric meaningless.
        """
        try:
            info = self.vehicle.get_collision(self.name)
        except Exception as exc:
            return {"available": False, "error": f"{type(exc).__name__}: {exc}"}

        collided = bool(getattr(info, "has_collided", False))
        stamp = getattr(info, "time_stamp", None)
        name = getattr(info, "object_name", "") if collided else ""

        record: dict[str, Any] = {
            "available": True,
            "has_collided": collided,
            # Did this happen during this flight, or is it left over from the
            # previous one? AirSim does not clear it between runs.
            "new_this_flight": bool(collided and stamp != self._collision_at_arm),
            "object": name,
            "is_ground": is_ground(name),
        }
        if collided:
            position = getattr(info, "impact_point", None)
            record.update({
                "penetration_depth": round(float(getattr(info, "penetration_depth", 0.0)), 3),
                "time_stamp": stamp,
                "impact_point": None if position is None else {
                    "x": round(position.x, 2),
                    "y": round(position.y, 2),
                    "z": round(position.z, 2),
                },
            })
        return record

    def arm(self) -> None:
        """Take control of the vehicle and record where the ground is."""
        # WAIT FOR THE DRONE TO STOP FALLING BEFORE BELIEVING THE GROUND.
        #
        # THIS MUST HAPPEN BEFORE enableApiControl. An unpowered drone falls to
        # the ground and stops there, which is the number we want. An ARMED one
        # does not: SimpleFlight catches it and holds it wherever it was. So
        # waiting after arming measures a hover, not the ground -- it reports
        # "settled" with complete confidence and is 17 m wrong. Measured
        # 2026-09-29: armed mid-fall at z=12.17, the controller arrested the
        # fall and held 12.20 indefinitely, 17.0 m above a ground at 29.25.
        #
        # Recorded before takeoff because this build has NO TERRAIN COLLISION:
        # the drone passes through the ground, so landing cannot wait for a
        # physical touchdown and must descend to a remembered height instead.
        # That makes this one number decide where every landing ends, and for
        # most of this project it has been wrong.
        #
        # client.reset() drops the drone at the player start, which sits about
        # 25 m above the terrain, and it falls. reset_world() waited a fixed
        # 2.0 s, which is not enough, so this line read a position taken in mid
        # air. Measured 2026-09-29 over three M01 runs: ground_z of 12.07,
        # 12.17 and 12.12 against a true ground of 29.25 -- an 18 m error,
        # consistent every run because the fall is deterministic. Landing then
        # descended to ground_z - 1.0 and stopped 18 m above the ground, which
        # is the drone "hovering in the air" seen throughout this project.
        # Block A recorded 10.87-11.02, the same error, so its 24 flights
        # ended in mid air too.
        #
        # So sample until the drone stops moving rather than trusting a delay.
        # The timeout means this can never hang; if it expires the value is
        # used anyway but flagged, because a silently wrong number is what
        # caused the problem in the first place.
        #
        # This is also the only simulator state the agent reads, and it never
        # reaches the model. The agent is blind by design.
        self.ground_settled = False
        previous = self.vehicle.get_state(self.name).position.z
        deadline = time.time() + GROUND_SETTLE_TIMEOUT
        while time.time() < deadline:
            time.sleep(0.3)
            current = self.vehicle.get_state(self.name).position.z
            if abs(current - previous) < GROUND_SETTLE_TOLERANCE:
                previous = current
                self.ground_settled = True
                break
            previous = current
        self.ground_z = previous

        # Cross-check against the session, and ADOPT what it returns. The settle
        # loop cannot tell an aircraft resting on the ground from one held
        # motionless above it, so this is the only thing standing between a bad
        # reading and a whole run of altitudes measured against it.
        #
        # Adopting the return matters when another drone has already found a
        # lower ground: this run then uses that one instead of its own. It does
        # NOT help when the bad reading arms first -- measured 2026-10-06, Drone3
        # arming with -0.18 before Drone1 found 29.25, and flying its whole
        # mission against it. Only `land`'s own verification catches that, which
        # it did: the run failed loudly rather than being recorded as valid. A
        # barrier that armed every drone before fixing the ground would close it
        # properly, and is not written yet.
        register_ground(self.name, self.ground_z)
        if self.barrier is not None:
            # Wait for the others to measure. A broken or timed-out barrier is not
            # fatal on its own: validate_grounds below still compares whatever was
            # registered, and the per-drone history check still applies.
            try:
                self.barrier.wait(timeout=GROUND_BARRIER_TIMEOUT)
            except Exception:
                pass
        validate_grounds(self.name)
        self.ground_z = check_ground_reference(self.name, self.ground_z)

        # Only now take control, with the drone at rest on the ground.
        self.vehicle.take_control(self.name)
        try:
            self._collision_at_arm = self.vehicle.get_collision(self.name).time_stamp
        except Exception:
            self._collision_at_arm = None
        self._say(f"armed, ground z = {self.ground_z:.2f}"
                  + ("" if self.ground_settled else "  [DID NOT SETTLE]"))

    def take_off(self) -> None:
        """Lift off and settle at cruise height before the plan begins."""
        self.vehicle.execute_skill(self.name, SkillCommand.take_off())
        # Every altitude is relative to the GROUND, not to z=0. Town10HD's
        # ground sits at NED z = +29.25, so a bare moveToZAsync(-8) climbs to
        # 37.5 m rather than 8 m. Measured 2026-10-06; see the phase log.
        self.vehicle.execute_skill(self.name, SkillCommand.move_to_z(
            self.ground_z + CRUISE_ALTITUDE, self.speed))
        # Settle before executing: a velocity command issued mid-climb produces
        # a curve rather than the straight leg the plan describes.
        time.sleep(TAKEOFF_SETTLE)

    def _velocity(self, vx: float, vy: float, duration: float) -> None:
        """Fly a body-frame velocity leg at a HELD altitude, then stop.

        Body frame means vx is forward RELATIVE TO THE DRONE'S HEADING, not
        north. Since nothing in this agent ever yaws, the two coincide here --
        but a future change that adds turning will make them diverge.

        Vertical drift during a leg is a known, UNFIXED defect, and its cause is
        NOT this call. vz = 0 commands zero vertical velocity rather than a held
        height, which costs about a metre -- measured 2026-10-06 on one drone,
        same 5 s leg from 18 m: backward +1.24 m, forward +1.40 m.

        But M10's Drone3 gains +14.6 m on this same leg, three runs running, and
        THAT IS NOT DRIFT -- do not try to fix it here. Traced at 10 Hz: the
        aircraft holds 19.9-20.0 m for three seconds and then goes 19.96 ->
        32.62 between t+18.06 and t+18.50. 12.7 m in 0.44 s, about 29 m/s, at a
        commanded 5 m/s, arriving at Drone1's altitude while its x continues
        smoothly. One discontinuity, not a climb.

        It needs backward flight AND other vehicles present: flying Drone3
        forward in the same four-drone layout gives 1.85 m and zero contacts,
        and one drone flying backward alone gives 1.24 m. Cause unknown.

        Two things known, for whoever picks this up:

        - `moveByVelocityZBodyFrameAsync`, holding the current z, was tried and
          made it worse: Drone3 still climbed to 31.42 m and the run hung in
          `land`, Drone1 released at 31.18 m and falling. Reverted.
        - `moveByVelocityZAsync` in the WORLD frame measured better on both axes
          than this call: +0.16 m of drift against +1.24 m, and 23.58 m travelled
          against 15.57 m for a leg asking 25. Body-frame velocity under-travels
          to 62% of the commanded distance, which nothing scores. World frame is
          equivalent here only because nothing in this agent yaws.

        That hypothesis -- no settle after `set_altitude`, so the leg inherits
        climb momentum -- was TESTED and is insufficient: no settle drifts
        +1.85 m with -4.17 m/s at the leg start, a 3 s settle drifts +1.06 m.
        Worth 0.8 m of the 14 m, so worth doing on its own merits and not the
        cause.

        The whole four-drone case reproduces through `fly_plans` with hand-built
        PlanRecords and no model -- Drone3 drifting 14.06 m against 14.6 -- so
        bisecting this needs a simulator and nothing else.

        See the phase log for 2026-10-06.
        """
        self.vehicle.execute_skill(self.name, SkillCommand.velocity(vx, vy, duration))
        # Velocity commands do not brake -- they expire and the aircraft coasts.
        # Without this hover, every leg overshoots by however far momentum
        # carries it, and the overshoot compounds across a multi-step plan.
        self.vehicle.stop(self.name)

    def step(self, step: dict[str, Any]) -> None:
        """Execute one validated plan step.

        One branch per action. Adding an action means adding a branch HERE as
        well as to ACTIONS, PLAN_SCHEMA, SYSTEM_PROMPT and validate() -- five
        places, or the model will emit something this method cannot fly.

        Every call is synchronous (`.join()`): within one drone the plan is a
        sequence, and concurrency happens between drones, not inside one.
        """
        action = step["action"]
        if action == "fly_straight":
            self._velocity(self.speed, 0.0, step["duration"])
        elif action == "fly_backward":
            self._velocity(-self.speed, 0.0, step["duration"])
        elif action == "fly_right":
            self._velocity(0.0, self.speed, step["duration"])
        elif action == "fly_left":
            self._velocity(0.0, -self.speed, step["duration"])
        elif action == "hover":
            self.vehicle.execute_skill(self.name, SkillCommand.hover())
            time.sleep(step["duration"])
        elif action == "set_altitude":
            # ground_z-relative: the plan says "30 m up", which means 30 m above
            # the ground the drone armed on, not 30 m above the map origin.
            self.vehicle.execute_skill(self.name, SkillCommand.move_to_z(
                self.ground_z + step["z"], self.speed))
        elif action == "fly_to":
            # BOUNDED, for the same reason `land` is. An unbounded
            # moveToPositionAsync against an obstacle does not fail -- it waits
            # forever, holding the worker thread, which holds the main thread,
            # which makes Ctrl-C impossible because the interrupt cannot be
            # delivered into a blocked RPC call. Observed 2026-10-09: two drones
            # pinned against a hotel at 5 m/s, and the only exit was killing the
            # simulator.
            #
            # The timeout is generous: a 300 m leg at MOVE_SPEED is 60 s, so this
            # cannot cut short a journey that was going to arrive.
            self.vehicle.execute_skill(self.name, SkillCommand.move_to_position(
                float(step["x"]), float(step["y"]),
                self.ground_z + float(step.get("z", CRUISE_ALTITUDE)),
                self.speed, FLY_TO_TIMEOUT))
        elif action == "land":
            # Descend to just above the remembered ground height first, slowly
            # (2 m/s rather than MOVE_SPEED), then hand over to landAsync. Going
            # straight to landAsync from cruise means a fast descent onto a
            # surface the physics does not model.
            self.vehicle.execute_skill(self.name, SkillCommand.move_to_z(
                self.ground_z - 1.0, 2.0, LAND_DESCENT_TIMEOUT))
            self.vehicle.execute_skill(self.name, SkillCommand.land(LAND_TIMEOUT))
            # VERIFY, and raise if it did not land. Both calls above can return
            # having moved the aircraft nowhere: measured 2026-10-06, moveToZAsync
            # running 27.1 s and returning with the aircraft still at 54.17 m when
            # asked for 1 m, then landAsync returning in 0.2 s from the same
            # place, after which control was released and the aircraft was left
            # airborne.
            #
            # Raising matters more than it looks. Teardown skips its own landing
            # when the plan's last step was a successful `land` -- `skip_landing`
            # is passed exactly then -- so a `land` that reports success without
            # landing disables the one safeguard against releasing control in
            # mid air. Failing here makes teardown do its job.
            agl = self._agl()
            if agl is not None and agl > LANDED_AGL_MAX:
                raise PlanError(
                    f"land did not descend: {agl:.2f} m above ground "
                    f"(target {LANDED_AGL_MAX} m). The aircraft is still flying.")
        else:  # unreachable: validate() rejects unknown actions
            raise PlanError(f"unhandled action {action!r}")

    def fly(self, steps: list[dict[str, Any]]) -> dict[str, Any]:
        """Arm, take off, execute the whole plan, then land and release control.

        Returns an execution record: which steps ran, which failed, and how long
        it took. The plan record says what the model produced; this says what the
        aircraft did, and 1.3 needs both -- a correct plan that fails in flight
        is not a successful mission.

        This is the thread body. It never raises: an exception here would die
        inside a worker thread where nobody sees it, leaving the vehicle armed
        and under API control with no way to fly it manually. So failures are
        caught, reported, and teardown runs in `finally` regardless.

        Teardown lands the aircraft if it is still airborne -- see
        `_land_and_release`. That landing is NOT a plan step and is not scored.

        The plan is executed to the end. A step that fails does NOT cancel the
        rest -- open loop means exactly that, and pretending otherwise would
        quietly make this a different architecture.
        """
        started = time.time()
        executed: list[str] = []
        altitudes: list[dict[str, Any]] = []
        failure: str | None = None
        try:
            self.arm()
            self.take_off()
            altitudes.append({"after": "take_off", "agl": self._agl()})
            for position, step in enumerate(steps, start=1):
                self._say(f"{position}/{len(steps)} {step['action']}")
                self.step(step)
                executed.append(step["action"])
                # Read immediately: moveToZAsync has joined, so this is the
                # height the step actually achieved, against the height asked
                # for. A set_altitude step records both and they must agree.
                altitudes.append({
                    "after": step["action"],
                    "agl": self._agl(),
                    "asked_agl": (round(-float(step["z"]), 2)
                                  if step["action"] == "set_altitude" else None),
                })
            # A plan without a final land leaves the drone airborne. Hover to
            # stop it drifting on whatever velocity the last step left behind;
            # teardown then brings it down.
            if steps[-1]["action"] != "land":
                self._say("plan ended without land; holding")
                self.vehicle.stop(self.name)
        except Exception as exc:
            failure = f"{type(exc).__name__}: {exc}"
            self._say(f"FAILED: {failure}")
        finally:
            # If the plan's last step was a successful `land`, the aircraft is
            # already coming down and teardown must not land it again. Trusting
            # the plan beats polling the vehicle: `landAsync` returns before
            # AirSim updates `landed_state`, so a state check right here reports
            # "flying" for an aircraft that is metres off the ground and
            # descending.
            ended_landed = bool(executed) and executed[-1] == "land" and failure is None
            self._land_and_release(skip_landing=ended_landed)

        # Read once, after teardown, and used twice: to decide whether the
        # aircraft is on the ground, and in the record. Calling it twice would
        # risk the two disagreeing.
        collision = self.collisions()

        # Where the aircraft actually finished. Recorded because for most of
        # this project every flight ended roughly 17 m above the ground and
        # nothing in the data showed it -- the run said "completed", the plan
        # was correct, and the only witness was somebody watching the screen.
        # A record that cannot show a drone hovering in mid air is not evidence.
        try:
            final = self.vehicle.get_pose(self.name)
            final_position = {"x": round(final.x, 2),
                              "y": round(final.y, 2),
                              "z": round(final.z, 2)}
            # TWO WAYS TO BE ON THE GROUND, because one of them is not enough.
            #
            # The height test compares against ground_z, which was read where
            # the drone ARMED. That is only the right reference if the terrain
            # is flat between there and wherever it came down, and Town10HD is
            # not. Measured 2026-10-06: a landed drone rests about 1.2 m above
            # its arming ground_z, so a 1.5 m window leaves only 0.3 m of
            # margin -- and M05, which flies 25 m out, landed on terrain 0.8 m
            # higher and read 1.99 m. Three perfectly good flights were flagged
            # as not having landed.
            #
            # So the simulator's own terrain contact is accepted as proof. If
            # the physics engine says the aircraft is touching ground, it has
            # landed, whatever a height taken 25 m away suggests. is_ground()
            # already separates terrain from obstacles, which is what makes
            # this safe: hitting a building would not satisfy it.
            touching_ground = bool(collision.get("has_collided")
                                   and collision.get("is_ground"))
            landed_on_ground = abs(final.z - self.ground_z) < 1.5 or touching_ground
        except Exception:
            final_position, landed_on_ground = None, None

        return {
            "drone": self.name,
            "planned": [s["action"] for s in steps],
            "executed": executed,
            # Completed means every step ran, not that the outcome was correct.
            "completed": len(executed) == len(steps) and failure is None,
            "failure": failure,
            "flight_seconds": round(time.time() - started, 1),
            "ground_z": round(self.ground_z, 2),
            "step_altitudes_agl": altitudes,
            "final_position": final_position,
            # True if the aircraft ended near its own ground height OR the
            # simulator reports it touching terrain. See the note above.
            "landed_on_ground": landed_on_ground,
            # False means the drone was still moving when the ground was
            # read, so every altitude in this run is suspect.
            "ground_settled": self.ground_settled,
            # Read after teardown so a collision during the landing is caught.
            "collision": collision,
        }

    def _agl(self) -> float | None:
        """Height above the arming ground, in metres. None if unreadable.

        Recorded after every step because the record could previously show where
        a flight ENDED but never how high it went, which is exactly how an
        altitude error of 29.25 m survived 30 runs and four sessions: every plan
        was correct, every flight completed, and no field disagreed.
        """
        try:
            z = self.vehicle.get_state(self.name).position.z
            return round(self.ground_z - z, 2)
        except Exception:
            return None

    def _is_airborne(self) -> bool:
        """True if the vehicle still needs landing before control is released.

        Asks AirSim for its landed state first. A height comparison alone is
        unreliable here: `landAsync` returns before the aircraft has fully
        settled, so a plan ending in `land` looked airborne to a z-check and got
        landed a second time -- harmless, but it added a redundant descent to
        every mission that lands, and would have appeared in every 1.3 run and
        every recording.
        """
        try:
            state = self.vehicle.get_state(self.name)
        except Exception:
            # If the state cannot be read, assume airborne: attempting a landing
            # that was not needed is harmless, skipping one that was is not.
            return True

        # HEIGHT IS AUTHORITATIVE, not LandedState. AirSim reports
        # LandedState = Landed for a motionless vehicle regardless of height:
        # measured 2026-10-06 with the aircraft hovering at 29.43 m above the
        # terrain and reporting Landed, and again on an M01 run that released
        # control at 9.32 m and dropped the aircraft. That is the same failure
        # `_land_and_release` was written to prevent, reintroduced by trusting
        # the field.
        #
        # The redundant-descent problem that motivated LandedState is already
        # handled by `skip_landing`, which the caller passes when the plan's own
        # last step was a successful `land` -- so height can be trusted here
        # without bringing it back. NED: more negative is higher.
        if state.position.z < self.ground_z - AIRBORNE_MARGIN:
            return True

        # Low enough to be down. Defer to LandedState if it disagrees, since a
        # needless landing is harmless and a skipped one is not.
        landed_state = getattr(state, "landed_state", None)
        return landed_state is not None and landed_state != 0

    def _land_and_release(self, skip_landing: bool = False) -> None:
        """Bring the aircraft down, then hand control back.

        `skip_landing` is passed when the plan itself ended with a successful
        `land`, so the descent is already under way.

        THIS IS TEARDOWN, NOT PART OF THE PLAN. It runs after the plan has
        finished, or after it failed, and it is not scored: the plan is what the
        model produced, and landing safely afterwards is the harness's job.

        It exists because disarming cuts the motors. Doing that while the
        aircraft is hovering -- which is exactly how a plan without a final
        `land` ends -- drops it out of the sky. Found on the first real flight:
        M01 took off, flew its leg, held position, and then fell when control
        was released.
        """
        try:
            if not skip_landing and self._is_airborne():
                self._say("teardown: landing before releasing control")
                self.step({"action": "land"})
        except Exception as exc:
            # Report and continue to the release: leaving the vehicle armed and
            # under API control is worse than an ungraceful landing.
            self._say(f"teardown landing failed: {type(exc).__name__}: {exc}")

        # Best effort, and silent if it fails: if the connection is already gone
        # there is nothing useful to do, and raising here would mask whatever
        # failure was reported above.
        try:
            self.vehicle.release(self.name)
            self._say("control released")
        except Exception:
            pass


# ---------------------------------------------------------------- flying them

def fly_plans(scene: Any, records: list[Any],
              connect: Callable[[], VehicleAdapter],
              runner_class: type[DroneRunner] = DroneRunner,
              speed: float = MOVE_SPEED,
              ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Fly one validated plan per drone, concurrently. Returns (outcomes, separation).

    `scene` resets and populates the world (a SceneAdapter that can also read
    vehicle state). `connect` opens a NEW VehicleAdapter, one per flight
    thread and one for the monitor. `records` need `.drone` and `.plan`.
    `runner_class` and `speed` exist so the sandbox can swap in its own
    runner and speed; the study uses the defaults.

    Shared by the interactive agent and the mission runner ON PURPOSE. If the
    two flew missions differently -- a different thread model, a different
    monitor, a different teardown -- then scored runs and hand-flown runs would
    not be the same experiment, and nobody would notice until the numbers
    disagreed.
    """
    # Create any drone this mission needs that the simulator does not have, and
    # refuse if it holds one the mission does not use. Runs here, after any
    # reset, so it sees the scene the flight will actually start in.
    ensure_vehicles(scene, [r.drone for r in records])

    outcomes: list[dict[str, Any]] = []
    lock = threading.Lock()

    def run(record: PlanRecord) -> None:
        # ITS OWN CONNECTION. See connect(): a shared client fails with
        # IOLoop and BufferError exceptions under concurrent use, and both
        # drones stay on the ground.
        own = connect()
        outcome = runner_class(own, record.drone, barrier, speed).fly(record.plan)
        with lock:                     # list.append is atomic, but be explicit
            outcomes.append(outcome)

    # Runs for every mission, not just multi-drone ones: proximity needs two
    # drones but collisions need one, and collisions are only visible while they
    # are happening. Started before the threads so the climb is covered.
    #
    # ALWAYS its own connection, even for a single drone. It polls at 10 Hz while
    # the flight threads issue commands, and sharing one msgpack-rpc socket
    # across threads is the open question this file has carried since 2026-09-24.
    # Not something to find out about through a rare, unreproducible failure.
    # One barrier for the whole run, so no drone takes off before every drone's
    # ground reading is in. See DroneRunner.arm.
    barrier = threading.Barrier(len(records)) if len(records) > 1 else None

    monitor = SeparationMonitor(connect(), [r.drone for r in records])
    monitor.start()

    threads = [threading.Thread(target=run, args=(r,)) for r in records]
    for thread in threads:
        thread.start()
    # Join every thread before returning: exiting with drones still flying
    # leaves them armed and under API control.
    for thread in threads:
        thread.join()

    separation = monitor.stop()

    # ---------------------------------------------------- landing, re-decided
    #
    # `landed_on_ground` is computed inside fly() from ONE post-teardown read of
    # simGetCollisionInfo, and that read is timing-dependent: AirSim clears
    # has_collided once contact ends, so whether the flag is still set when
    # fly() looks is luck.
    #
    # It matters for exactly one mission. M05 flies 25 m out, where the terrain
    # is about 0.8 m higher than where it armed, so it comes to rest 2.01 m
    # above its arming ground_z and fails the 1.5 m height test. Its landing
    # therefore rests entirely on contact evidence.
    #
    # Measured: identical flights, 22.2 s and a final height of 27.24 in both,
    # reported landed on 2026-10-09 and NOT landed on 2026-10-19. The 9 October
    # block's "24/24 landed" was true by coincidence rather than by measurement.
    #
    # The 10 Hz poll does not have the problem -- it caught the terrain contact
    # at t+21.94 of a 22.2 s flight -- so the landing check now uses it. The
    # single read is kept as the first test, because when it fires it is
    # correct; the poll only ever adds evidence, never removes it.
    polled = separation.get("collisions_polled") or []
    for outcome in outcomes:
        outcome["landed_evidence"] = "height or contact at teardown"
        if outcome["landed_on_ground"]:
            continue
        contact = landing_contact(outcome["drone"], outcome["flight_seconds"],
                                  polled)
        if contact:
            outcome["landed_on_ground"] = True
            outcome["landed_evidence"] = (
                "polled ground contact with %s at t+%.2fs"
                % (contact["object"], contact["last_at_s"]))

    # A separation figure only exists when there were two drones to measure
    # between. The monitor runs for a single drone as well, because collisions
    # need polling and proximity simply does not apply -- so `measured` being
    # true says the thread ran, not that there is a distance to report.
    # Printing it unconditionally gave "closest approach: None m at t+Nones" on
    # every single-drone run, which is 24 of the 30 in the mission set.
    if separation.get("min_separation_m") is not None:
        print(f"\nclosest approach: {separation['min_separation_m']} m "
              f"at t+{separation['min_separation_at_s']}s "
              f"({separation['samples']} samples)")
    elif separation["measured"]:
        contacts = len(separation.get("collisions_polled") or [])
        print(f"\nmonitored {separation['samples']} samples, "
              f"{contacts} contact(s); one drone, so no separation to report")
    return outcomes, separation
