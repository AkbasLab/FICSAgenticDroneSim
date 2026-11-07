#!/usr/bin/env python3
"""Phase 17's calibration: which communication levels are meaningful, by docs/CONDITIONS.md's pre-registered rule.

    python scripts/calibrate_conditions.py                # the sweep (configs/experiments/phase17_calibration.toml)
    python scripts/calibrate_conditions.py --batch-dir runs/experiments/phase17-calibration-<stamp>   # judge again

Flies the sweep with the batch runner (A, B, C; 2 and 4 drones; every level; no failure and Drone1 stopped;
development seeds 1-20; the mock), scores it with docs/METRICS.md, and applies docs/CONDITIONS.md's rule
(`experiments/calibration.py`). Outputs, under phases/phase-17-pilot-experiments/results/ by default:

    calibration-<stamp>.json / .md     each level's verdict and why, each arm's statistics, the levels chosen
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from agentic_uav.experiments.batch import DEFAULT_ROOT, run_batch  # noqa: E402
from agentic_uav.experiments.calibration import judge  # noqa: E402
from agentic_uav.experiments.experiment import load_batch  # noqa: E402
from agentic_uav.experiments.metrics import batch_metrics, doc_sha256, write_metrics  # noqa: E402
from agentic_uav.experiments.provenance import file_digest, provenance  # noqa: E402

BATCH = "phase17_calibration"
RULE = os.path.join(REPO, "docs", "CONDITIONS.md")
DEFAULT_OUT = os.path.join(REPO, "phases", "phase-17-pilot-experiments", "results")


def delivery(batch_dir: str, run_id: str) -> tuple[int, int]:
    got = lost = 0
    with gzip.open(os.path.join(batch_dir, run_id, "events.jsonl.gz"), "rt", encoding="utf-8") as h:
        for line in h:
            if '"MESSAGE_RECEIVED"' in line:
                got += 1
            elif '"MESSAGE_DROPPED"' in line:
                lost += 1
    return got, lost


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--jobs", type=int, default=10)
    parser.add_argument("--batch-dir", help="judge an already flown sweep instead of flying it")
    parser.add_argument("--work", default=DEFAULT_ROOT)
    parser.add_argument("--out", default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
    started, code = time.strftime("%Y-%m-%dT%H:%M:%S"), provenance()
    batch_dir = args.batch_dir or run_batch(load_batch(BATCH), args.work, jobs=args.jobs, progress=lambda s: None)
    rows = batch_metrics(batch_dir)
    write_metrics(batch_dir, rows)
    verdict = judge(rows, {r["run_id"]: delivery(batch_dir, r["run_id"]) for r in rows})
    record = {"t": started, "batch_dir": batch_dir, "runs": len(rows), "rule_sha256": file_digest(RULE),
              "metrics_sha256": doc_sha256(), "code": code, **verdict}
    os.makedirs(args.out, exist_ok=True)
    stem = f"calibration-{time.strftime('%Y%m%d-%H%M%S')}"
    with io.open(os.path.join(args.out, stem + ".json"), "w", encoding="utf-8", newline="\n") as h:
        json.dump(record, h, indent=1, default=str)
    lines = [f"# Calibration — docs/CONDITIONS.md version {verdict['version']}", "",
             f"Run {started}; {len(rows)} runs (`{BATCH}`), development seeds 1-20, the mock.", ""]
    for team, levels in verdict["levels"].items():
        lines += [f"## {team} drones", "", "| Level | Meaningful | Not easy | Not hard | Distinguishable | Useful | Delivery |",
                  "|---|---|---|---|---|---|---|"]
        for lv, v in levels.items():
            c = v["checks"]
            yn = lambda b: "yes" if b else "**no**"  # noqa: E731
            lines.append(f"| {lv} | {yn(v['meaningful'])} | {yn(c['not_trivially_easy'])} | {yn(c['not_trivially_hard'])} | "
                         f"{yn(c['distinguishable'])} | {yn(c['communication_useful'])} | {100 * v['delivery_rate']:.1f} % |")
        lines += ["", f"**Pilot level:** {verdict['pilot'][team] or 'none by this version'} · "
                      f"**Phase 18 levels:** {', '.join(verdict['phase18'][team])}", ""]
        for lv, v in levels.items():
            lines.append(f"* {lv}: " + ("; ".join(v["signal"][:4]) or "no two arms apart"))
        lines.append("")
    lines += ["## Each arm", "", "| Team · level · failure · arm | Success | Median s (IQR) | Retention |", "|---|---|---|---|"]
    for k, s in verdict["stats"].items():
        p3 = "—" if s["p3"] is None else f"{s['p3']:.3f}"
        lines.append(f"| {k.replace('|', ' · ')} | {100 * s['success']:.0f} % | {s['median_s']:.1f} "
                     f"({s['iqr_s'][0]:.1f}–{s['iqr_s'][1]:.1f}) | {p3} |")
    with io.open(os.path.join(args.out, stem + ".md"), "w", encoding="utf-8", newline="\n") as h:
        h.write("\n".join(lines) + "\n")
    print("\n".join(lines[:40]))
    print(f"record  : {os.path.join(args.out, stem + '.json')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
