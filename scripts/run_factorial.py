"""Run the Phase 18 factorial experiment, resumably, and report every cell.

    python scripts/run_factorial.py configs/experiments/factorial_dev.yaml           # pipeline check
    python scripts/run_factorial.py configs/experiments/factorial_main.yaml --dry-run
    python scripts/run_factorial.py configs/experiments/factorial_main.yaml           # stage 1
    python scripts/run_factorial.py configs/experiments/factorial_main.yaml --stage 2 # 8 drones
    python scripts/run_factorial.py configs/experiments/factorial_main.yaml --only _D_   # one architecture

Safe to stop and restart: a run whose directory is already complete and valid
under the current freeze is not run again. An excluded run is retried with the
same seed, up to the predeclared limit. Writes, under results/<design_id>/:

    <run>/ ...             every run's complete result directory (incl. llm/)
    runs.csv               one line per run: verdict, exclusion reason, outcomes
    cells.csv              valid replications per cell, against the requirement
    exclusions.csv         every exclusion and the criterion that caused it
    by_network.csv         architecture x network   (18: the key comparisons)
    by_failure.csv         architecture x failure
    report.md              all of the above, readable
    design_manifest.json   design, exclusion criteria and freeze fingerprints

Exit code 0 only when every cell has enough valid replications.
"""

import argparse
import csv
import json
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agentic_uav.experiments import factorial as fx
from agentic_uav.experiments.experiment_runner import ROOT, run_experiment
from agentic_uav.experiments.freeze import fingerprint, snapshot

#: Rough per-run costs on a desktop, for --dry-run. A model call is ~6 s for
#: llama3.1:8b on the pilot machine (benchmark: 5.8 s mean).
SECONDS_PER_MOCK_RUN = 0.3
MODEL_CALLS_PER_D_RUN = {2: 15, 4: 30, 8: 60}
SECONDS_PER_MODEL_CALL = {"scripted": 0.0, "default": 6.0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("design")
    ap.add_argument("--stage", default="1", choices=["1", "2", "all"])
    ap.add_argument("--out", default=None)
    ap.add_argument("--only", default=None, help="run only ids containing this text")
    ap.add_argument("--limit", type=int, default=None, help="stop after N runs")
    ap.add_argument("--dry-run", action="store_true", help="count runs and estimate cost")
    args = ap.parse_args()

    design = fx.load_design(args.design)
    excl = fx.load_exclusions(os.path.join(ROOT, design.get("exclusions", "configs/experiments/exclusion_criteria.yaml")))
    out = args.out or os.path.join(ROOT, "results", design["design_id"])
    configs = fx.expand(design, args.stage)
    if args.only:
        configs = [c for c in configs if args.only in c.experiment_id]

    planner = str(design.get("planner", "scripted"))
    n_d = sum(1 for c in configs if c.architecture_key == "D")
    calls = sum(MODEL_CALLS_PER_D_RUN.get(c.team_size, 30) for c in configs
                if c.architecture_key == "D")
    per_call = SECONDS_PER_MODEL_CALL.get(planner, SECONDS_PER_MODEL_CALL["default"])
    est = len(configs) * SECONDS_PER_MOCK_RUN + calls * per_call
    print(f"Design {design['design_id']} ({design['split']} split), stage {args.stage}: "
          f"{len(fx.cells(design, args.stage))} cells x {len(fx.seeds(design))} seeds = "
          f"{len(configs)} runs ({n_d} agentic, planner {planner})")
    print(f"Estimated time: ~{est / 3600:.1f} h"
          + (f" (~{calls} model calls at ~{per_call:.0f} s)" if per_call else ""))
    if args.dry_run:
        return 0

    fp = fingerprint(snapshot())
    seal = fx.check_test_split(design, fp, excl)        # raises if not allowed
    if seal:
        print(f"Held-out split - sealed configuration from {seal['sealed_at']}")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "design_manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"design": {k: v for k, v in design.items() if not k.startswith("_")},
                   "design_sha256": design["_sha256"],
                   "exclusions_sha256": excl["_sha256"], "freeze_fingerprint": fp,
                   "stage": args.stage, "started_at": time.strftime("%Y-%m-%dT%H:%M:%S")},
                  f, indent=1, default=str)

    rows, ran, started = [], 0, time.monotonic()
    max_attempts = int(excl.get("max_attempts_per_run", 3))
    for i, cfg in enumerate(configs, 1):
        directory = os.path.join(out, cfg.experiment_id)
        verdict = None
        attempt = 1
        if os.path.exists(os.path.join(directory, "manifest.json")):
            verdict = fx.classify(directory, cfg, excl, fp)
            prev = _attempts(directory)
            attempt = prev
            if verdict["status"] == "valid":
                rows.append(fx.row(cfg, directory, verdict, attempt))
                continue                      # resume: already done
            if prev >= max_attempts:
                rows.append(fx.row(cfg, directory, verdict, attempt))
                continue
        if args.limit is not None and ran >= args.limit:
            break
        while True:
            if os.path.isdir(directory):
                keep = os.path.join(out, "_excluded_attempts",
                                    f"{cfg.experiment_id}__attempt{attempt}")
                if os.path.exists(keep):
                    shutil.rmtree(keep)
                os.makedirs(os.path.dirname(keep), exist_ok=True)
                shutil.move(directory, keep)  # an exclusion keeps its evidence
                attempt += 1
            run_experiment(cfg, out_root=out)
            _set_attempts(directory, attempt)
            ran += 1
            verdict = fx.classify(directory, cfg, excl, fp)
            if verdict["status"] == "valid" or attempt >= max_attempts:
                break
        rows.append(fx.row(cfg, directory, verdict, attempt))
        mark = "ok " if verdict["status"] == "valid" else "EXC"
        print(f"[{i:>4}/{len(configs)}] {mark} {cfg.experiment_id}"
              + (f"  ({verdict['reasons'][0][:70]})" if verdict["reasons"] else ""), flush=True)

    cells = fx.sufficiency(rows, design, excl, args.stage)
    _csv(os.path.join(out, "runs.csv"), rows)
    _csv(os.path.join(out, "cells.csv"), cells)
    _csv(os.path.join(out, "exclusions.csv"),
         [r for r in rows if r["status"] != "valid"] or [{"experiment_id": "-", "exclusion": "none"}])
    by_net = fx.comparison(rows, "network")
    by_fail = fx.comparison(rows, "failure")
    _csv(os.path.join(out, "by_network.csv"), by_net)
    _csv(os.path.join(out, "by_failure.csv"), by_fail)
    _report(os.path.join(out, "report.md"), design, excl, rows, cells, by_net, by_fail, args.stage)

    short = [c for c in cells if not c["sufficient"]]
    print(f"\n{ran} run(s) executed this time, {len(rows)} recorded, "
          f"{time.monotonic() - started:.0f}s.")
    print(f"Cells with enough valid replications: {len(cells) - len(short)}/{len(cells)}")
    print(f"Wrote {os.path.join(out, 'report.md')}")
    return 0 if not short else 1


def _attempts(directory):
    try:
        with open(os.path.join(directory, ".attempt"), encoding="utf-8") as f:
            return int(f.read().strip() or 1)
    except (OSError, ValueError):
        return 1


def _set_attempts(directory, n):
    try:
        with open(os.path.join(directory, ".attempt"), "w", encoding="utf-8") as f:
            f.write(str(n))
    except OSError:
        pass


def _csv(path, rows):
    if not rows:
        return
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def _f(m, sd, d=2):
    return "--" if m is None else f"{m:.{d}f} ± {sd:.{d}f}"


def _report(path, design, excl, rows, cells, by_net, by_fail, stage):
    valid = [r for r in rows if r["status"] == "valid"]
    short = [c for c in cells if not c["sufficient"]]
    need = cells[0]["required"] if cells else excl.get("min_valid_per_cell")
    L = [f"# Factorial experiment {design['design_id']} ({design['split']} split, stage {stage})", "",
         f"- runs recorded: {len(rows)}; valid: {len(valid)}; excluded: {len(rows) - len(valid)}",
         f"- system failures (an exception in the system under test - kept as a failed "
         f"mission, not excluded): {sum(1 for r in rows if r['system_failure'])}",
         f"- cells with at least {need} valid replications: {len(cells) - len(short)}/{len(cells)}",
         f"- planner: {design.get('planner')}; common random numbers: on; "
         f"faults interrupt skills: {design.get('fault_interrupts_skill', True)}",
         f"- exclusion criteria: `{os.path.relpath(excl['_path'], ROOT)}` "
         f"(sha256 {excl['_sha256']}) - technical only, declared in advance", ""]
    for title, data, factor in (("Architecture × communication condition", by_net, "network"),
                                ("Architecture × failure condition", by_fail, "failure")):
        L += [f"## {title}", "", f"| arch | {factor} | n | success | coverage | dup sectors | time (s) |",
              "|---|---|---|---|---|---|---|"]
        for r in data:
            L.append(f"| {r['architecture']} | {r[factor]} | {r['n']} | {100 * r['success_rate']:.0f}% "
                     f"| {_f(r['coverage_mean'], r['coverage_sd'])} "
                     f"| {_f(r['duplicated_sectors_mean'], r['duplicated_sectors_sd'], 1)} "
                     f"| {_f(r['mission_time_s_mean'], r['mission_time_s_sd'], 0)} |")
        L.append("")
    L += ["## Cells short of valid replications", ""]
    L += [f"- {c['architecture']} n{c['team_size']} {c['network']} {c['failure']}: "
          f"{c['valid']}/{c['required']} valid ({c['run']} run, {c['excluded']} excluded)"
          for c in short] or ["None - every cell has enough valid replications."]
    L += ["", "## Exclusions", ""]
    ex = [r for r in rows if r["status"] != "valid"]
    L += [f"- {r['experiment_id']} (attempt {r['attempt']}): {r['exclusion']}" for r in ex] or ["None."]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


if __name__ == "__main__":
    sys.exit(main())
