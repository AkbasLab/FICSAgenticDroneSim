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

from fics_drone.agents.llm_backends import ScriptedBackend
from fics_drone.agents.ollama_backend import OllamaBackend
from fics_drone.experiments.experiment_config import ExperimentConfig
from fics_drone.experiments.experiment_runner import run_experiment
from run_dynamic_zone_study import DEFAULT_SCENARIO, MOCK_SPEED_MPS

GUARDIAN_KEYS = ("commands", "interventions", "intervention_rate", "steer_outs",
                 "steer_out_distance_m", "zone_interrupts", "failed_checks")
MISSION_KEYS = ("coverage", "targets_found", "zone_exposure_s", "mission_s", "all_home")


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
    parser.add_argument("--out-root", default=None,
                        help="where the experiment folder goes (default runs/experiments)")
    parser.add_argument("--tag", default=time.strftime("%Y%m%d_%H%M%S"),
                        help="suffix that keeps experiment ids unique")
    args = parser.parse_args()

    if args.backend == "scripted":
        backend, card = ScriptedBackend(), None   # plumbing check only: no model, nothing to pin
    else:
        backend = OllamaBackend(args.model)
        card = backend.card()
        for warning in card.warnings():
            print(f"WARNING: {warning}")
        print(f"loading {args.model} ...", flush=True)
        print(f"  ready in {backend.warm_up():.1f}s", flush=True)

    cfg = ExperimentConfig(f"zonellm_{args.only}_{args.backend}_{args.tag}", zone_profile=args.only,
                           scenario=args.scenario, repeats=1, mock_speed_mps=MOCK_SPEED_MPS,
                           policy=args.backend, model=args.model, llm_timeout_s=args.timeout,
                           appear_s=args.appear_s, expire_s=args.expire_s, drift_s=args.drift_s)
    kwargs = {"out_root": args.out_root} if args.out_root else {}
    experiment = run_experiment(cfg, backend=backend, llm_save_dir=args.save, **kwargs)
    if experiment.error:
        sys.exit(f"experiment failed:\n{experiment.error}")

    run = experiment.runs[0]
    violations = run["mission"]["no_fly_violations"]
    mission = {k: run["mission"][k] for k in MISSION_KEYS}
    mission["no_fly_violation_samples"] = (len(violations) if isinstance(violations, (list, tuple))
                                           else violations)
    result = {"guardian": {k: run["guardian"][k] for k in GUARDIAN_KEYS},
              "model": run["model"], "mission": mission}
    print(json.dumps(result, indent=2))
    if args.save:
        with open(os.path.join(args.save, "results.json"), "w") as f:
            json.dump({"condition": args.only, "model_card": card.to_dict() if card else None,
                       "backend": args.backend, "monitor": True,
                       "zone_times_s": {"appear": args.appear_s, "expire": args.expire_s,
                                        "drift": args.drift_s},
                       "result": result}, f, indent=2)
        print(f"\nsaved to {args.save}")
    print(f"recorded in {experiment.directory}")


if __name__ == "__main__":
    main()
