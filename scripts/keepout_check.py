#!/usr/bin/env python3
"""Phase 9's stop flights again, with the keep-out round a silent teammate (the fix for its live collision).

    python scripts/keepout_check.py                   # seeds 1-20
    python scripts/keepout_check.py --seeds 17 --block t

What is flown and checked is in `experiments/keepout_check.py`: each seed, the
canonical four with each drone stopped at 60 s (twice each), and the live
variant's pair with Drone2 stopped at 17 s (the live flight's mock twin), with
the keep-out and the guardian on; and the four with no stop, against Phase 9's
own flight. Checked: Phase 9's eight checks, on the four and on the twin; no
survivor enters the keep-out; the guardian never intervenes; with no stop,
nothing changes.

Outputs, under phases/phase-09-roles-and-failure-recovery/results/ by default:

    keepout-check-<stamp>[-<block>].jsonl   a header (the manifests, the verdict); per seed the checks and findings
    keepout-check-<stamp>[-<block>].md      the checks, the closest passes, the verdict

Exit code 0 only if every check passed on every seed.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from agentic_uav.coordination.keepout import parse_keepout  # noqa: E402
from agentic_uav.experiments.allocation import allocation_path, load_allocation  # noqa: E402
from agentic_uav.experiments.guardian_exit import guardian_path, load_guardian  # noqa: E402
from agentic_uav.experiments.keepout_check import (  # noqa: E402
    CHECKS,
    TWIN_SCENARIO,
    keepout_checks,
    keepout_findings,
    keepout_flights,
)
from agentic_uav.experiments.provenance import provenance  # noqa: E402
from agentic_uav.experiments.recovery import load_recovery, recovery_path  # noqa: E402
from agentic_uav.experiments.runner import load_toml  # noqa: E402
from agentic_uav.experiments.scenarios import load_scenario  # noqa: E402
from agentic_uav.experiments.search_relay import EXIT_SEEDS  # noqa: E402

DEFAULT_OUT = os.path.join(REPO, "phases", "phase-09-roles-and-failure-recovery", "results")
KEEPOUT = os.path.join(REPO, "configs", "keepout", "default.toml")
SCENARIO = "search_relay_001"


def seeds_arg(text: str) -> tuple[int, ...]:
    out: list[int] = []
    for part in text.split(","):
        if "-" in part:
            a, b = part.split("-", 1)
            out += range(int(a), int(b) + 1)
        else:
            out.append(int(part))
    return tuple(out)


def rel(path: str) -> str:
    return os.path.relpath(path, REPO).replace(os.sep, "/")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seeds", type=seeds_arg, default=EXIT_SEEDS)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--block", metavar="LABEL")
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    scenario, twin = load_scenario(SCENARIO), load_scenario(TWIN_SCENARIO)
    config, health, limits = load_allocation(), load_recovery(), load_guardian()
    keep_out = parse_keepout(load_toml(KEEPOUT), KEEPOUT)
    wall = time.perf_counter()
    rows = []
    for seed in args.seeds:
        flights = keepout_flights(scenario, twin, seed, config, health, limits, keep_out)
        checks = keepout_checks(flights, keep_out)
        rows.append({"kind": "seed", "seed": seed, "checks": checks, "findings": keepout_findings(flights, keep_out)})
        print(f"seed {seed}: " + ", ".join(f"{k} {'yes' if checks[k]['ok'] else 'NO'}" for k in CHECKS), flush=True)
    wall = time.perf_counter() - wall
    ok = all(r["checks"]["all"] for r in rows)

    passes = [(k, p) for r in rows for k, f in r["findings"].items() for p in f["passes"]]
    def low(field):
        return min((p[field] for _, p in passes), default=None)

    header = {"kind": "header", "t": started, "scenario": scenario.scenario_id, "twin": twin.scenario_id,
              "allocation_manifest": rel(allocation_path()), "recovery_manifest": rel(recovery_path()),
              "guardian_manifest": rel(guardian_path()), "keepout_manifest": rel(KEEPOUT),
              "keep_out": keep_out.as_json(), "limits": limits.as_json(), "seeds": list(args.seeds),
              "seeds_passed": sum(r["checks"]["all"] for r in rows), "all_passed": ok,
              "closest_to_heard_m": low("closest_to_heard_m"), "closest_to_true_m": low("closest_to_true_m"),
              "heard_vs_true_m_max": max((p["heard_vs_true_m"] for _, p in passes), default=None),
              "wall_s": round(wall, 2), "code": provenance()}

    lines = [f"# Keep-out check — {scenario.scenario_id} and {twin.scenario_id}, mock", "",
             f"Run {started}, `scripts/keepout_check.py`, {wall:.1f} s wall. Keep-out {keep_out.half_width_m:g} m "
             f"either side of a teammate silent {keep_out.after_s:g} s in the air, with the guardian; the four with "
             "each drone stopped at 60 s (twice each) and with no stop; the live pair's twin with Drone2 stopped at "
             "17 s (twice).", "",
             "| Seed | " + " | ".join(CHECKS) + " |", "|---|" + "---|" * len(CHECKS)]
    for r in rows:
        lines.append(f"| {r['seed']} | " + " | ".join("yes" if r["checks"][k]["ok"] else "**no**" for k in CHECKS) + " |")
    lines += ["", f"**Closest passes over every seed and stop** (findings): to where the stopped drone was last heard, "
                  f"{header['closest_to_heard_m']} m; to where it truly hovered, {header['closest_to_true_m']} m "
                  f"(last heard up to {header['heard_vs_true_m_max']} m from where it truly stopped).", "",
              f"**{'ALL PASSED' if ok else 'NOT ALL PASSED'}** — {header['seeds_passed']} of {len(rows)} seeds passed "
              "every check.", ""]
    problems = [f"seed {r['seed']}, {k}: {p}" for r in rows for k in CHECKS for p in r["checks"][k]["problems"]]
    if problems:
        lines += ["Problems:", ""] + [f"* {p}" for p in problems[:50]] + [""]

    os.makedirs(args.out, exist_ok=True)
    stem = f"keepout-check-{time.strftime('%Y%m%d-%H%M%S')}" + (f"-{args.block}" if args.block else "")
    with io.open(os.path.join(args.out, stem + ".jsonl"), "w", encoding="utf-8", newline="\n") as h:
        for row in [header] + rows:
            h.write(json.dumps(row, default=str) + "\n")
    with io.open(os.path.join(args.out, stem + ".md"), "w", encoding="utf-8", newline="\n") as h:
        h.write("\n".join(lines))
    print("\n".join(lines))
    print(f"raw     : {os.path.join(args.out, stem + '.jsonl')}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
