"""Phase 11: the catalogue run is the fast check (nothing flies); --live adds
a compromised-policy mission and proves containment end to end, including
when the policy never recovers (--repeat).

    python scripts/run_guardian_demo.py                        # catalogue; nothing flies
    python scripts/run_guardian_demo.py --live                 # + compromised-policy mission
    python scripts/run_guardian_demo.py --case nan_waypoint    # one case in isolation
    python scripts/run_guardian_demo.py --live --repeat        # policy stays broken throughout
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fics_drone.agents.belief import Belief
from fics_drone.agents.belief_schema import MissionBelief, SelfState
from fics_drone.agents.safety_guardian import Command, FallbackAction, GuardianOutcome, SafetyGuardian, SafetyLimits
from fics_drone.agents.unsafe_injection import CATALOGUE, belief_for_case
from fics_drone.core.scenario import load_scenario
from fics_drone.experiments.guardian_log import GuardianLog

DEFAULT_SCENARIO = os.path.join(os.path.dirname(__file__), "..", "configs", "missions",
                                 "search_relay_001.json")


def build_guardian(scenario_path):
    scenario = load_scenario(scenario_path)
    return SafetyGuardian(limits=SafetyLimits.from_scenario(scenario))


def run_catalogue(scenario_path, only_case=None):
    blocked = 0
    total = 0
    for case in CATALOGUE:
        if only_case and case.name != only_case:
            continue
        total += 1
        guardian = build_guardian(scenario_path)  # fresh guardian per case - no cross-case state
        belief = belief_for_case(case.name)
        evaluation = guardian.evaluate(case.build(), belief)
        caught = case.expects_check in evaluation.failed_checks
        if caught:
            blocked += 1
        status = "caught" if caught else "MISSED"
        print(f"  [{status}] {case.name}: outcome={evaluation.outcome.value} "
              f"failed_checks={evaluation.failed_checks}")
    print(f"\nblocked {blocked}/{total} (every unsafe command stopped)" if blocked == total else
          f"\nblocked {blocked}/{total} - SOME UNSAFE COMMANDS WERE NOT CAUGHT")
    return blocked, total


class InjectingPolicy:
    """Substitutes unsafe commands into a live mission so containment can be
    observed end to end - nothing here is used in normal operation."""

    def __init__(self, repeat: bool = False, break_after: int = 1, unsafe_run: int = 6):
        self.repeat = repeat
        self.break_after = break_after
        self.unsafe_run = unsafe_run
        self._unsafe = [case.build() for case in CATALOGUE]

    def propose(self, step: int, position) -> Command:
        x, y, z = position
        if step < self.break_after:
            return Command(kind="fly", target=(x + 2.0, y, z), speed_mps=5.0, timeout_s=30.0)
        if not self.repeat and step >= self.break_after + self.unsafe_run:
            # Recovered: finish the mission properly - head home, then land, rather
            # than proposing the same stationary point forever (which would never
            # land and make "recovery" meaningless).
            if abs(x) > 3.0 or abs(y) > 3.0:
                return Command(kind="fly", target=(0.0, 0.0, z), speed_mps=5.0, timeout_s=30.0, purpose="home")
            return Command(kind="land", target=(x, y, 0.0))
        return self._unsafe[step % len(self._unsafe)]


def run_live_mission(scenario_path, repeat: bool):
    guardian = build_guardian(scenario_path)
    log = GuardianLog()
    policy = InjectingPolicy(repeat=repeat)
    belief = Belief(self_state=SelfState(position=(10.0, 10.0, 8.0), elapsed_s=0.0, battery_s=100.0),
                     mission=MissionBelief(sector_id="A", search_queue=[]))

    step = 0
    landed = False
    MAX_STEPS = 100
    while step < MAX_STEPS and not landed:
        command = policy.propose(step, belief.position)
        evaluation = guardian.evaluate(command, belief)
        log.record(step, command, evaluation)

        if evaluation.outcome in (GuardianOutcome.APPROVE, GuardianOutcome.APPROVE_WITH_MODIFICATION,
                                   GuardianOutcome.EXECUTE_SAFE_FALLBACK):
            if evaluation.command.kind == "fly" and evaluation.command.target is not None:
                belief.position = evaluation.command.target
            elif evaluation.command.kind == "land":
                landed = True
            if evaluation.outcome == GuardianOutcome.EXECUTE_SAFE_FALLBACK and \
                    evaluation.fallback == FallbackAction.LAND_AT_SAFE_LOCATION:
                landed = True
            guardian.command_completed()
        # REJECT_AND_REPLAN: nothing executed, nothing in flight - no command_completed() needed

        step += 1

    # Invariant this whole phase exists to prove: a command with ANY failed check is
    # never executed unmodified. APPROVE means zero failed checks by construction, so
    # this should always be 0 - computed from the log rather than hardcoded so a future
    # change to evaluate() that broke the invariant would show up here, not get assumed away.
    unsafe_reached_vehicle = sum(
        1 for e in log.entries if e.outcome == GuardianOutcome.APPROVE.value and e.failed_checks)
    print(log.format_summary())
    print(f"\nunsafe commands that reached the vehicle: {unsafe_reached_vehicle}")
    print(f"drone landed safely at home: {landed and abs(belief.position[0]) < 3.0 and abs(belief.position[1]) < 3.0}")
    return log, landed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", default=DEFAULT_SCENARIO)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--repeat", action="store_true")
    parser.add_argument("--case", default=None)
    args = parser.parse_args()

    if args.case:
        run_catalogue(args.scenario, only_case=args.case)
        return

    if not args.live:
        run_catalogue(args.scenario)
        return

    run_catalogue(args.scenario)
    print()
    run_live_mission(args.scenario, repeat=args.repeat)


if __name__ == "__main__":
    main()
