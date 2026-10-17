"""Does the simulator-free suite actually catch defects? (Phase 16 exit criterion)

The exit criterion for Phase 16 is that *most coordination and communication
defects can be discovered without launching CARLA-Air*. That is a claim about
the test suite, and a test suite cannot be trusted to assess itself by passing.
A suite of 400 assertions that all pass proves only that nothing it checks is
broken right now - it says nothing about whether it would notice if something
broke.

So this measures it directly. Each defect below is a one-line change to a real
coordination or communication invariant, applied to a throwaway copy of the
repository. The simulator-free suites are then run against the damaged copy,
and the defect counts as caught if at least one of them fails. Nothing is
installed, nothing is flown, and the working tree is never modified.

    python scripts/run_defect_injection.py              # all defects
    python scripts/run_defect_injection.py --list       # just list them
    python scripts/run_defect_injection.py --only lease # one, by name

Exit code is 0 only if every defect was caught. An uncaught defect is the
useful output of this script: it names a property the suite claims to care
about but would not notice losing.

A defect that *cannot* be expressed as a small source change is out of scope
here, and so is anything requiring the real simulator - this measures the
simulator-free suite against the kind of mistake a person actually makes while
editing coordination code.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Suites run against each damaged copy. The AirSim-path suite is excluded: it
#: takes 40 s and its subject is the adapter, not coordination, so including it
#: would quadruple the runtime of this script for no additional sensitivity.
SUITES = [
    "tests/test_allocation.py",
    "tests/test_roles_recovery.py",
    "tests/test_network.py",
    "tests/test_messaging.py",
    "tests/test_guardian.py",
    "tests/test_llm_policy.py",
    "tests/test_belief_state.py",
    "tests/test_integration.py",
    "tests/test_determinism.py",
    "tests/test_architectures.py",
]

#: (name, area, file, find, replace, what the defect does)
#:
#: Each `find` is matched exactly once; a mutation that no longer matches its
#: source is reported as a broken defect rather than a caught one, so this
#: catalogue cannot silently rot into always-passing.
DEFECTS = [
    ("tie_break", "allocation",
     "agentic_uav/coordination/bidding.py",
     "        return self.vehicle_id < other.vehicle_id",
     "        return self.vehicle_id > other.vehicle_id",
     "ties break on the highest vehicle ID instead of the lowest, so two "
     "agents ordering the same bids disagree about the winner"),

    ("bid_ignores_distance", "allocation",
     "agentic_uav/coordination/bidding.py",
     "        distance_term = min(d / MAX_RANGE_M, 1.0)",
     "        distance_term = 0.0",
     "distance stops affecting the bid, so a drone no longer prefers the "
     "sector it is closest to and the division of work degenerates towards "
     "the tie-breaker"),

    ("lease_never_expires", "allocation",
     "agentic_uav/coordination/tasks.py",
     "        return now >= self.lease_expires_at",
     "        return False",
     "a task held by a silent agent is never released, so work is lost "
     "permanently rather than being picked up by a teammate"),

    ("conflict_rule_order", "allocation",
     "agentic_uav/coordination/task_allocator.py",
     '                rule = "lower_bid"',
     '                rule = "lower_bid"  # noqa\n'
     '                winner_task = local',
     "the conflict rules stop agreeing on a winner, so two agents can both "
     "believe they hold the same task"),

    ("message_never_expires", "communication",
     "agentic_uav/coordination/protocols.py",
     "        return now >= self.expires_at",
     "        return False",
     "a message is delivered however stale it is, so an agent can act on a "
     "position report from several minutes ago"),

    ("no_packet_loss", "communication",
     "agentic_uav/coordination/network_model.py",
     '        if loss > 0 and self.rng.random() < min(loss, 1.0):\n'
     '            return self._drop("packet_loss")',
     "        if False:\n"
     '            return self._drop("packet_loss")',
     "the configured packet loss is ignored, so every degraded condition is "
     "quietly run as a perfect one"),

    ("partitions_ignored", "communication",
     "agentic_uav/coordination/network_model.py",
     "            if part.blocks(sender, recipient, now):",
     "            if False and part.blocks(sender, recipient, now):",
     "partitions never block anything, so the partitioned condition is "
     "indistinguishable from the nominal one"),

    ("base_reachability_range_only", "communication",
     "agentic_uav/simulator/ground_truth.py",
     "        return bool(self._network.base_reachable_for(vehicle_id, now))",
     "        return in_range",
     "base reachability goes back to being distance-only, so a partitioned "
     "drone believes it can still reach base and no drone ever relays "
     "(this is the defect Phase 16.2 found)"),

    ("failure_on_first_miss", "roles",
     "agentic_uav/coordination/roles.py",
     "FAILED_AFTER_MISSED = 8.0",
     "FAILED_AFTER_MISSED = 1.0",
     "a single missed heartbeat declares a teammate dead, so sectors are "
     "pulled off healthy drones that were briefly quiet"),

    ("beliefs_never_stale", "belief",
     "agentic_uav/agents/belief_schema.py",
     "        return self.status_confidence(now) < threshold",
     "        return False",
     "no record is ever considered stale, so an old peer position is treated "
     "as current - including by the separation check"),

    ("geofence_always_passes", "safety",
     "agentic_uav/agents/safety_guardian.py",
     "    def _check_separation(self, target, belief) -> SafetyCheck:",
     "    def _check_geofence(self, target) -> SafetyCheck:\n"
     '        return SafetyCheck("geofence", True, "disabled")\n\n'
     "    def _check_separation(self, target, belief) -> SafetyCheck:",
     "the geofence check passes everything, so a command outside the "
     "operating area reaches the vehicle"),

    # --- defects first found in real CARLA-Air runs ----------------------
    # Each was invisible to the suite when it was found, and seen only by
    # flying. They are here so the exit criterion covers what the simulator
    # taught us, not just what we thought to test for. Each is now caught by
    # the fake simulator, without launching CARLA-Air.
    ("airsim_frame_offset", "simulator",
     "agentic_uav/simulator/airsim_adapter.py",
     "        return Position3D(p.x_val + ox, p.y_val + oy, p.z_val)",
     "        return Position3D(p.x_val, p.y_val, p.z_val)",
     "positions are passed through in each drone's own spawn frame, so four "
     "drones spawned 4 m apart all report (0, 0, 0) and every bid is identical",
     ["tests/test_airsim_path.py::"
      "test_positions_are_reported_and_commanded_in_world_coordinates"]),

    ("dropped_moves_not_resent", "simulator",
     "agentic_uav/simulator/airsim_adapter.py",
     "    MAX_RESENDS = 3",
     "    MAX_RESENDS = 0",
     "a move the simulator returns from without moving counts as a navigation "
     "failure, and three of them make a drone abandon its sector",
     ["tests/test_airsim_path.py::"
      "test_dropped_moves_are_resent_and_the_sweep_completes"]),

    ("sweep_timeout_per_leg", "skills",
     "agentic_uav/control/skill_executor.py",
     "            leg_timeout = min(max(remaining, 1.0),\n"
     "                              STALL_FACTOR * expected + STALL_ALLOWANCE_S)",
     "            leg_timeout = command.timeout_s",
     "every leg of a sweep gets the whole skill's timeout, so a pinned drone "
     "waits ten minutes per leg",
     ["tests/test_skills.py"]),

    ("no_stand_by_for_teammates", "recovery",
     "agentic_uav/agents/persistent_agent.py",
     "        if outstanding:",
     "        if False and outstanding:",
     "survivors land as soon as their own work is done, before a lost "
     "teammate is noticed, and its sector is never searched",
     ["tests/test_airsim_regression.py::test_4_task_reassignment_during_flight"]),

    ("completion_gossip_ignored", "communication",
     "agentic_uav/coordination/task_allocator.py",
     '        elif t is MessageType.STATUS_UPDATE and p.get("completed"):',
     "        elif False:",
     "a lost TASK_COMPLETE is never repaired, so standing-by drones wait on "
     "finished work and a lapsed lease sends a drone to re-fly it",
     ["tests/test_allocation.py"]),
]


def _suite_fails(workdir, suite, timeout_s=300):
    """True if the suite reports failure in the damaged copy.

    `suite` is a test file, or `file::function` to run one test - used for the
    AirSim-path defects, whose test files are too slow to run whole for every
    injected defect.
    """
    cmd = [sys.executable, suite]
    if "::" in suite:
        path, func = suite.split("::", 1)
        mod = os.path.splitext(os.path.basename(path))[0]
        cmd = [sys.executable, "-c", (
            "import sys; sys.path.insert(0, 'tests'); sys.path.insert(0, '.')\n"
            f"import {mod} as m\n"
            "from agentic_uav.simulator import fake_airsim\n"
            "try:\n"
            f"    m.{func}()\n"
            "except AssertionError as e:\n"
            "    print('FAIL', e); sys.exit(1)\n"
            "finally:\n"
            "    fake_airsim.uninstall()\n")]
    try:
        p = subprocess.run(cmd, cwd=workdir,
                           capture_output=True, text=True, timeout=timeout_s,
                           env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                           encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        # A hang is a detection too: the suite noticed, by not finishing.
        return True, "timeout"
    if p.returncode != 0:
        first = ""
        for line in (p.stdout + p.stderr).splitlines():
            s = line.strip()
            if s.startswith("FAIL") or "Error" in s or "assert" in s:
                first = s[:90]
                break
        return True, first or f"exit {p.returncode}"
    return False, ""


def _copy_repo(dst):
    def ignore(d, names):
        return [n for n in names
                if n in ("__pycache__", ".git", "results", "runs", ".pytest_cache")
                or n.endswith(".pyc")]
    shutil.copytree(ROOT, dst, ignore=ignore, dirs_exist_ok=True)


def run_defect(defect, verbose=False):
    name, area, path, find, replace, _why = defect[:6]
    suites = defect[6] if len(defect) > 6 else SUITES
    with tempfile.TemporaryDirectory(prefix=f"defect_{name}_") as tmp:
        work = os.path.join(tmp, "repo")
        _copy_repo(work)

        target = os.path.join(work, path)
        with open(target, encoding="utf-8") as f:
            src = f.read()
        if src.count(find) != 1:
            return {"name": name, "area": area, "status": "BROKEN",
                    "detail": f"pattern matched {src.count(find)} times in {path}",
                    "caught_by": []}
        with open(target, "w", encoding="utf-8") as f:
            f.write(src.replace(find, replace))

        caught_by = []
        for suite in suites:
            failed, detail = _suite_fails(work, suite)
            if failed:
                caught_by.append((os.path.basename(suite), detail))
                if not verbose:
                    break        # one detection is enough; stop early for speed
        return {"name": name, "area": area,
                "status": "caught" if caught_by else "MISSED",
                "detail": caught_by[0][1] if caught_by else "no suite failed",
                "caught_by": caught_by}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="list the defects and exit")
    ap.add_argument("--only", help="run one defect by name")
    ap.add_argument("--verbose", action="store_true",
                    help="report every suite that catches each defect")
    args = ap.parse_args()

    defects = DEFECTS
    if args.only:
        defects = [d for d in DEFECTS if d[0] == args.only]
        if not defects:
            print(f"no defect named {args.only!r}; have: "
                  f"{', '.join(d[0] for d in DEFECTS)}")
            return 2

    if args.list:
        for name, area, path, _f, _r, why, *_ in DEFECTS:
            print(f"{name:32s} [{area}]  {path}\n    {why}")
        return 0

    print("Defect injection - can the simulator-free suite find these?\n")
    results = []
    for d in defects:
        r = run_defect(d, verbose=args.verbose)
        results.append(r)
        mark = {"caught": "ok   ", "MISSED": "MISS ", "BROKEN": "BROKE"}[r["status"]]
        print(f"  {mark} {r['name']:32s} {r['detail'][:60]}", flush=True)
        if args.verbose and r["caught_by"]:
            for suite, detail in r["caught_by"]:
                print(f"           {suite:30s} {detail[:50]}")

    caught = [r for r in results if r["status"] == "caught"]
    missed = [r for r in results if r["status"] == "MISSED"]
    broken = [r for r in results if r["status"] == "BROKEN"]

    print(f"\n{len(caught)}/{len(results)} defects caught without the simulator")
    if missed:
        print("\nMISSED - the suite would not notice these:")
        for r in missed:
            why = next(d[5] for d in DEFECTS if d[0] == r["name"])
            print(f"  {r['name']}: {why}")
    if broken:
        print("\nBROKEN - the injection no longer matches the source:")
        for r in broken:
            print(f"  {r['name']}: {r['detail']}")
        print("  (the code moved; update the catalogue so it keeps testing "
              "something real)")
    return 0 if not missed and not broken else 1


if __name__ == "__main__":
    sys.exit(main())
