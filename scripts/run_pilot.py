"""Run the Phase 17 pilot matrix, draw every timeline, and audit every log.

    python scripts/run_pilot.py configs/experiments/pilot_matrix.yaml
    python scripts/run_pilot.py configs/experiments/pilot_matrix.yaml --no-plots
    python scripts/run_pilot.py configs/experiments/pilot_matrix.yaml --only C_n4_severe

Writes, under results/<pilot_id>/:

    <run>/...              the normal result directory, plus timeline.png
    pilot_summary.csv      one line per cell: mean +/- sd over seeds
    pilot_runs.csv         one line per run
    pilot_report.md        cells, findings per run, and the log audit

Exit code 0 when every run completed *and* every log passed the audit - the
"complete, interpretable logs" half of the Phase 17 exit criterion.
"""

import argparse
import csv
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agentic_uav.experiments import pilot
from agentic_uav.experiments.experiment_runner import ROOT, run_experiment


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("matrix")
    ap.add_argument("--out", default=None, help="default results/<pilot_id>")
    ap.add_argument("--no-plots", action="store_true")
    ap.add_argument("--only", default=None,
                    help="run only experiment ids containing this text")
    args = ap.parse_args()

    matrix = pilot.load_matrix(args.matrix)
    out = args.out or os.path.join(ROOT, "results", matrix["pilot_id"])
    configs = pilot.expand(matrix)
    if args.only:
        configs = [c for c in configs if args.only in c.experiment_id]
    print(f"Pilot {matrix['pilot_id']}: {len(configs)} runs -> {out}\n")

    rows, started = [], time.monotonic()
    for i, cfg in enumerate(configs, 1):
        res = run_experiment(cfg, out_root=out)
        audit = pilot.audit_run(res.directory)
        if not args.no_plots:
            try:
                from agentic_uav.experiments import timeline
                tl = timeline.build_timeline(timeline.load_run(res.directory))
                timeline.plot(tl, os.path.join(res.directory, "timeline.png"))
            except Exception as e:                              # noqa: BLE001
                audit["problems"].append(f"timeline plot failed: {e}")
        r = res.result.as_row() if res.result else {}
        row = {"experiment_id": cfg.experiment_id,
               "architecture": cfg.architecture_key, "team_size": cfg.team_size,
               "network": cfg.network_profile, "seed": cfg.random_seed,
               **{k: r.get(k) for k in pilot.METRICS},
               "stopped": r.get("stopped"),
               "success": pilot.success(r, cfg.team_size),
               "audit_problems": "; ".join(audit["problems"]),
               "findings": " | ".join(audit["findings"])}
        rows.append(row)
        flag = "OK " if not audit["problems"] else "LOG"
        print(f"[{i:>2}/{len(configs)}] {flag} {res.summary()}", flush=True)
        for f in audit["findings"]:
            print(f"          - {f}")
        for p in audit["problems"]:
            print(f"          ! {p}")

    cells = pilot.summarise(rows)
    os.makedirs(out, exist_ok=True)
    _csv(os.path.join(out, "pilot_runs.csv"), rows)
    _csv(os.path.join(out, "pilot_summary.csv"), cells)
    report = os.path.join(out, "pilot_report.md")
    _report(report, matrix, rows, cells)

    bad = [r for r in rows if r["audit_problems"]]
    print(f"\n{len(rows)} runs in {time.monotonic() - started:.0f}s. "
          f"Logs complete: {len(rows) - len(bad)}/{len(rows)}.")
    print(f"Wrote {report}")
    return 1 if bad else 0


def _csv(path, rows):
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def _fmt(m, sd, d=2):
    return "--" if m is None else f"{m:.{d}f} ± {sd:.{d}f}"


def _report(path, matrix, rows, cells):
    L = [f"# Pilot {matrix['pilot_id']}", "",
         "Pilot runs debug the methodology. None of these numbers is a result.", "",
         f"- architectures: {', '.join(map(str, matrix['architectures']))}",
         f"- team sizes: {matrix['team_sizes']}",
         f"- networks: {', '.join(matrix['network_profiles'])}",
         f"- failure: {matrix['failure_profile']}",
         f"- seeds: {matrix['seeds']}",
         f"- planner: {matrix.get('planner', 'scripted')}", "",
         "## Cells (mean ± sd over seeds)", "",
         "| arch | drones | network | success | coverage | dup sectors | time (s) "
         "| delivery | seeds differ? | logs |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for c in cells:
        L.append(f"| {c['architecture']} | {c['team_size']} | {c['network']} "
                 f"| {100 * c['success_rate']:.0f}% "
                 f"| {_fmt(c['coverage_mean'], c['coverage_sd'])} "
                 f"| {_fmt(c['duplicated_sectors_mean'], c['duplicated_sectors_sd'], 1)} "
                 f"| {_fmt(c['mission_time_s_mean'], c['mission_time_s_sd'], 0)} "
                 f"| {_fmt(c['delivery_rate_mean'], c['delivery_rate_sd'])} "
                 f"| {'no - identical' if c['seeds_identical'] else 'yes'} "
                 f"| {c['runs'] - c['incomplete_logs']}/{c['runs']} complete |")
    L += ["", "## What the timelines show", ""]
    for r in rows:
        if r["findings"]:
            L.append(f"- **{r['experiment_id']}**: {r['findings']}")
    if not any(r["findings"] for r in rows):
        L.append("No automatic findings.")
    L += ["", "## Log audit", ""]
    bad = [r for r in rows if r["audit_problems"]]
    if not bad:
        L.append(f"All {len(rows)} result directories are complete: every file "
                 "present, every expected event type, per-drone task/role/position, "
                 "a flown track per drone, and the event stream agrees with the "
                 "reported sectors and duplicates.")
    for r in bad:
        L.append(f"- {r['experiment_id']}: {r['audit_problems']}")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


if __name__ == "__main__":
    sys.exit(main())
