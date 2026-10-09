"""GMB study: what does the guardian do when no-fly zones change during a mission?

    python scripts/run_dynamic_zone_study.py                   # 3 repeats per condition, mock
    python scripts/run_dynamic_zone_study.py --repeats 5 --save runs/dynamic_zone_mock

Four agents, deterministic policy, kinematic mock (nothing flies). Conditions differ ONLY in the
scenario's no-fly zones. Metrics were fixed before this was run (see
projects/akbas-lab/GMB_DYNAMIC_BOUNDARIES.md, decision 4):

  per run   guardian: commands evaluated, interventions, intervention rate, by outcome,
                      failed checks, steer-outs (exit_zone)
            mission:  coverage, targets found, no-fly violations, separation violations,
                      mission seconds, all home

This is a MOCK, DETERMINISTIC-POLICY pilot, so the numbers say what the guardian does, not what an
LLM policy does. Mission time is real wall-clock time (the mock moves in real time), so zone
timings are approximate and runs vary slightly.
"""

import argparse
import copy
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fics_drone.coordination.message_bus import MessageBus
from fics_drone.core.scenario import NoFlyZone, load_scenario
from fics_drone.evaluation.metrics import score_run
from fics_drone.experiments.team_runner import run_team_threaded
from fics_drone.simulator.kinematic_mock_adapter import KinematicMockVehicleAdapter
from fics_drone.telemetry.recorder import SAMPLE_RATE_HZ, TelemetryRecorder

DEFAULT_SCENARIO = os.path.join(os.path.dirname(__file__), "..", "configs", "missions",
                                 "search_relay_001.json")
MOCK_SPEED_MPS = 15.0


def conditions(base, appear_s=5.0, expire_s=12.0, drift_s=3.0):
    """name -> scenario. Zones are placed over Sector A (x 20-40, y 20-40), where Drone1 searches."""
    def with_zone(zone):
        s = copy.deepcopy(base)
        s.no_fly_zones = list(s.no_fly_zones) + [zone]
        return s

    return {
        # control: the original scenario, one static zone far from every sector
        "static": copy.deepcopy(base),
        # a zone switches ON over most of Sector A partway through the mission
        "appear": with_zone(NoFlyZone("DZ_appear", 24.0, 40.0, 24.0, 40.0, active_from_s=appear_s)),
        # same zone, but it switches off again, so the sector becomes searchable afterwards
        "appear_expire": with_zone(NoFlyZone("DZ_appear", 24.0, 40.0, 24.0, 40.0,
                                              active_from_s=appear_s, active_until_s=expire_s)),
        # a small zone drifting across Sector A
        "drift": with_zone(NoFlyZone("DZ_drift", 38.0, 46.0, 28.0, 36.0, active_from_s=drift_s, vx=-2.5)),
    }


def run_once(scenario, monitor=True):
    adapters = {d.name: KinematicMockVehicleAdapter(d.name, speed_mps=MOCK_SPEED_MPS) for d in scenario.drones}
    offsets = {d.name: d.spawn_offset for d in scenario.drones}
    recorder = TelemetryRecorder(adapters, world_offsets=offsets)
    recorder.start()
    start = time.monotonic()
    reports, agents, _bus = run_team_threaded(scenario, adapters, bus=MessageBus(),
                                              agent_kwargs={"zone_monitor": monitor})
    elapsed = time.monotonic() - start
    # one more sample before stopping: at 5 Hz the last sample can be 0.2 s stale, which for a drone
    # moving at 15 m/s is ~3 m and made already-landed drones read as "not home" in ~1 run in 5
    time.sleep(2.0 / SAMPLE_RATE_HZ)
    recorder.stop()

    score = score_run(scenario, recorder.log, elapsed)

    # exposure: seconds spent inside any zone while it was active, summed over drones.
    # Samples are 1 / SAMPLE_RATE_HZ apart, so this is a count of samples converted to seconds.
    exposure_s = sum(1 for samples in recorder.log.values() for smp in samples
                     if any(z.contains(smp.position[0], smp.position[1], smp.t) for z in scenario.no_fly_zones)
                     ) / SAMPLE_RATE_HZ
    interrupts = sum(step == "zone_interrupt" for r in reports.values() for step in r.trace)

    entries = [e for a in agents.values() for e in a.guardian_log.entries]
    by_outcome, by_check = {}, {}
    for e in entries:
        by_outcome[e.outcome] = by_outcome.get(e.outcome, 0) + 1
        for name in e.failed_checks:
            by_check[name] = by_check.get(name, 0) + 1
    interventions = sum(1 for e in entries if e.outcome != "approve")
    return {
        "guardian": {
            "commands": len(entries),
            "interventions": interventions,
            "intervention_rate": round(interventions / len(entries), 3) if entries else 0.0,
            "by_outcome": by_outcome,
            "failed_checks": by_check,
            "steer_outs": sum(1 for e in entries if e.fallback == "exit_zone"),
            "steer_out_distance_m": round(sum(e.move_m for e in entries if e.move_m is not None), 1),
            "zone_interrupts": interrupts,
        },
        "mission": {
            "coverage": round(score.coverage_fraction, 3),
            "targets_found": score.targets_found,
            "no_fly_violations": score.no_fly_violations,
            "zone_exposure_s": round(exposure_s, 1),
            "separation_violations": len(score.separation_violations),
            "mission_s": round(elapsed, 1),
            "all_home": score.all_home,
            "overall_pass": score.overall_pass,
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", default=DEFAULT_SCENARIO)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--only", default=None, help="run one condition by name")
    parser.add_argument("--save", default=None, help="directory to write results.json into")
    args = parser.parse_args()

    base = load_scenario(args.scenario)
    results = {}
    for name, scenario in conditions(base).items():
        if args.only and name != args.only:
            continue
        for monitor in ((False,) if name == "static" else (False, True)):
            label = f"{name}/{'tick' if monitor else 'cmd '}"
            runs = []
            for i in range(args.repeats):
                r = run_once(scenario, monitor=monitor)
                runs.append(r)
                g, m = r["guardian"], r["mission"]
                print(f"{label:18} run {i + 1}: cmds {g['commands']:3} interventions {g['interventions']:2} "
                      f"steer-outs {g['steer_outs']} ({g['steer_out_distance_m']} m) interrupts {g['zone_interrupts']} | "
                      f"exposure {m['zone_exposure_s']}s | coverage {m['coverage']:.0%} targets {len(m['targets_found'])} "
                      f"{m['mission_s']}s home={m['all_home']}")
            results[label.strip()] = runs

    if args.save:
        os.makedirs(args.save, exist_ok=True)
        with open(os.path.join(args.save, "results.json"), "w") as f:
            json.dump({"repeats": args.repeats, "policy": "deterministic", "modes": "cmd = guardian acts at command boundaries only; tick = per-control-tick zone monitor", "adapter": "kinematic_mock",
                       "mock_speed_mps": MOCK_SPEED_MPS, "results": results}, f, indent=2)
        print(f"\nsaved to {args.save}/results.json")


if __name__ == "__main__":
    main()
