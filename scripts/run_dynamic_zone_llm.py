"""GMB study, LLM arm: the same dynamic-zone conditions as run_dynamic_zone_study.py, but each of
the four drones decides with a local Llama (Phase 12's LLMAgentPolicy over one shared Ollama).

    python scripts/run_dynamic_zone_llm.py --only appear --appear-s 40 --save runs/dynamic_zone_llm_appear

Slow by design: one Ollama process serves all four agents (~11 s per call on this laptop's CPU), so a
mission takes minutes, not seconds. Zone times are therefore in the SAME mission seconds but must be
set much later than the mock study's (--appear-s, --drift-s); the deterministic and LLM arms fly at
different paces, so compare WHAT THE GUARDIAN DID, not mission times.

Reports the guardian numbers the paper's RQ5 asks about (interventions, steer-outs and their distance,
zone exposure) next to the model's own (decisions, fallback rate, guardian blocks).
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from fics_drone.agents.llm_policy import make_policy_factory
from fics_drone.agents.llm_backends import ScriptedBackend
from fics_drone.agents.ollama_backend import OllamaBackend
from fics_drone.coordination.message_bus import MessageBus
from fics_drone.core.scenario import load_scenario
from fics_drone.evaluation.metrics import score_run
from fics_drone.experiments.llm_log import save_run, summarize
from fics_drone.experiments.team_runner import run_team_with_faults
from fics_drone.simulator.kinematic_mock_adapter import KinematicMockVehicleAdapter
from fics_drone.telemetry.recorder import SAMPLE_RATE_HZ, TelemetryRecorder
from run_dynamic_zone_study import DEFAULT_SCENARIO, MOCK_SPEED_MPS, conditions


def run_once(scenario, backend, card, timeout_s, save_dir=None):
    adapters = {d.name: KinematicMockVehicleAdapter(d.name, speed_mps=MOCK_SPEED_MPS) for d in scenario.drones}
    offsets = {d.name: d.spawn_offset for d in scenario.drones}
    recorder = TelemetryRecorder(adapters, world_offsets=offsets)
    factory, policies = make_policy_factory(backend, scenario, timeout_s=timeout_s)
    recorder.start()
    start = time.monotonic()
    reports, agents, _bus, _assign = run_team_with_faults(scenario, adapters, bus=MessageBus(),
                                                           heartbeat_interval_s=2.0, policy_factory=factory)
    elapsed = time.monotonic() - start
    # one more sample before stopping: at 5 Hz the last sample can be 0.2 s stale, which for a drone
    # moving at 15 m/s is ~3 m and made already-landed drones read as "not home" in ~1 run in 5
    time.sleep(2.0 / SAMPLE_RATE_HZ)
    recorder.stop()
    score = score_run(scenario, recorder.log, elapsed)

    entries = [e for a in agents.values() for e in a.guardian_log.entries]
    interventions = sum(1 for e in entries if e.outcome != "approve")
    exposure_s = sum(1 for samples in recorder.log.values() for smp in samples
                     if any(z.contains(smp.position[0], smp.position[1], smp.t) for z in scenario.no_fly_zones)
                     ) / SAMPLE_RATE_HZ
    decisions = [r for p in policies.values() for r in p.records]
    fallbacks = sum(1 for r in decisions if r.source == "fallback")
    out = {
        "guardian": {
            "commands": len(entries), "interventions": interventions,
            "intervention_rate": round(interventions / len(entries), 3) if entries else 0.0,
            "steer_outs": sum(1 for e in entries if e.fallback == "exit_zone"),
            "steer_out_distance_m": round(sum(e.move_m for e in entries if e.move_m is not None), 1),
            "zone_interrupts": sum(step == "zone_interrupt" for r in reports.values() for step in r.trace),
            "failed_checks": {n: sum(n in e.failed_checks for e in entries)
                              for n in {c for e in entries for c in e.failed_checks}},
        },
        "model": {"decisions": len(decisions), "fallbacks": fallbacks,
                  "fallback_rate": round(fallbacks / len(decisions), 3) if decisions else 0.0},
        "mission": {"coverage": round(score.coverage_fraction, 3), "targets_found": score.targets_found,
                    "zone_exposure_s": round(exposure_s, 1), "mission_s": round(elapsed, 1),
                    "all_home": score.all_home, "no_fly_violation_samples": len(score.no_fly_violations)},
    }
    if save_dir:
        save_run(save_dir, policies, agents, card.to_dict() if card else None)
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", default=DEFAULT_SCENARIO)
    parser.add_argument("--backend", choices=["ollama", "scripted"], default="ollama")
    parser.add_argument("--model", default="llama3.1:8b")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--only", default="appear", help="static | appear | appear_expire | drift")
    parser.add_argument("--appear-s", type=float, default=40.0)
    parser.add_argument("--expire-s", type=float, default=120.0)
    parser.add_argument("--drift-s", type=float, default=30.0)
    parser.add_argument("--save", default=None, help="directory for prompts/outputs and results.json")
    args = parser.parse_args()

    scenario = conditions(load_scenario(args.scenario), appear_s=args.appear_s, expire_s=args.expire_s,
                          drift_s=args.drift_s)[args.only]
    if args.backend == "scripted":
        backend, card = ScriptedBackend(), None   # plumbing check only: no model, nothing to pin
    else:
        backend = OllamaBackend(args.model)
        card = backend.card()
        for warning in card.warnings():
            print(f"WARNING: {warning}")
        print(f"loading {args.model} ...", flush=True)
        print(f"  ready in {backend.warm_up():.1f}s", flush=True)

    result = run_once(scenario, backend, card, args.timeout, save_dir=args.save)
    print(json.dumps(result, indent=2))
    if args.save:
        with open(os.path.join(args.save, "results.json"), "w") as f:
            json.dump({"condition": args.only, "model_card": card.to_dict() if card else None, "backend": args.backend, "monitor": True,
                       "zone_times_s": {"appear": args.appear_s, "expire": args.expire_s, "drift": args.drift_s},
                       "result": result}, f, indent=2)
        print(f"\nsaved to {args.save}")


if __name__ == "__main__":
    main()
