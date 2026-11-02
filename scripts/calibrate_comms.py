"""Calibrate the communication conditions (Phase 17.3).

    python scripts/calibrate_comms.py configs/networks/calibration_ladder.yaml
    python scripts/calibrate_comms.py configs/networks/calibration_ladder.yaml --write-final

Sweeps every level in the ladder, classifies it (useless / too weak / trivial /
flat / usable), picks the final nominal, moderate and severe levels from the
usable band, and explains each choice. Writes to results/calibration/:

    calibration.csv         every level x architecture
    calibration_report.md   the classification and the reasons for each choice
    calibration.png         duplicates and mission time against loss and latency

`--write-final` also writes configs/networks/final_profiles.yaml - the profiles
the final experiments use, which Phase 17.4 then freezes.
"""

import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agentic_uav.experiments import calibration as cal
from agentic_uav.experiments.experiment_runner import ROOT


def backend_for(key):
    if key != "D":
        return None
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    from run_llm_agents import sensible_model
    from agentic_uav.agents.llm_backends import ScriptedBackend
    return ScriptedBackend(default=sensible_model)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ladder")
    ap.add_argument("--out", default=os.path.join(ROOT, "results", "calibration"))
    ap.add_argument("--write-final", action="store_true")
    ap.add_argument("--no-plot", action="store_true")
    args = ap.parse_args()

    ladder = cal.load_ladder(args.ladder)
    levels = cal.levels_from(ladder)
    n = len(levels) * len(ladder["architectures"]) * len(ladder["seeds"])
    print(f"Calibrating {len(levels)} levels x {len(ladder['architectures'])} "
          f"architectures x {len(ladder['seeds'])} seeds = {n} runs\n")

    results = []
    for lv in levels:
        r = cal.run_level(lv, ladder, backend_factory=backend_for)
        results.append(r)
        parts = [f"{a} dup {s['dup_mean']:.1f}±{s['dup_sd']:.1f} t {s['time_mean']:.0f} "
                 f"clean {100 * s['clean_rate']:.0f}%"
                 for a, s in r.by_arch.items() if a != "B"]
        d = min(s["delivery_mean"] for a, s in r.by_arch.items() if a != "B")
        print(f"  {lv.name:12s} delivery {d:4.2f}  " + " | ".join(parts), flush=True)

    cal.classify(results, ladder)
    choice = cal.select(results)
    lines = cal.explain(choice, results)

    os.makedirs(args.out, exist_ok=True)
    _csv(os.path.join(args.out, "calibration.csv"), results)
    report = os.path.join(args.out, "calibration_report.md")
    _report(report, ladder, results, choice, lines)
    if not args.no_plot:
        _plot(os.path.join(args.out, "calibration.png"), results, choice)

    print("\nClassification")
    for r in results:
        verdict = "usable" if r.usable else ", ".join(r.flags)
        print(f"  {r.level.name:12s} {verdict:28s} {'; '.join(r.reasons)[:90]}")
    print("\nChosen levels")
    for line in lines:
        print(" ", line.replace("**", ""))

    if args.write_final:
        path = os.path.join(ROOT, "configs", "networks", "final_profiles.yaml")
        _write_final(path, choice, args.ladder)
        print(f"\nwrote {path}")
    print(f"\nwrote {report}")
    return 0 if choice["moderate"] and choice["severe"] else 1


def _csv(path, results):
    rows = []
    for r in results:
        for a, s in r.by_arch.items():
            rows.append({"level": r.level.name, "axis": r.level.axis,
                         "loss": r.level.profile.packet_loss_probability,
                         "latency_ms": r.level.profile.latency_ms_mean,
                         "rate_limit": r.level.profile.message_rate_limit or "",
                         "architecture": a, **{k: (round(v, 4) if isinstance(v, float) else v)
                                               for k, v in s.items()},
                         "verdict": "usable" if r.usable else "+".join(r.flags)})
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def _report(path, ladder, results, choice, lines):
    L = ["# Communication calibration (Phase 17.3)", "",
         f"{len(ladder['seeds'])} seeds per level; {ladder['team_size']} drones; "
         f"failure `{ladder['failure_profile']}`; architectures "
         f"{', '.join(ladder['architectures'])} (B never coordinates, so it is the "
         "'communication cannot help' reference). Clean success = every sector "
         "searched, every survivor home, no sector flown twice.", "",
         "## Chosen levels", ""] + lines + [
         "", f"Usable band on the loss axis: {', '.join(choice['usable_band']) or 'none'}.",
         "", "## Every level", "",
         "| level | loss | latency (ms) | delivery | C dup | C time (s) | D dup | D time (s) "
         "| verdict | why |", "|---|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        p = r.level.profile
        c, d = r.by_arch.get("C", {}), r.by_arch.get("D", {})
        deliv = min(s["delivery_mean"] for a, s in r.by_arch.items() if a != "B")
        def f(s, k, dd=1):
            return "--" if not s else f"{s[k + '_mean']:.{dd}f} ± {s[k + '_sd']:.{dd}f}"
        L.append(f"| {r.level.name} | {p.packet_loss_probability:.0%} "
                 f"| {p.latency_ms_mean:.0f}"
                 + (f" (rate {p.message_rate_limit:g}/s)" if p.message_rate_limit else "")
                 + f" | {deliv:.2f} | {f(c, 'dup')} | {f(c, 'time', 0)} "
                 f"| {f(d, 'dup')} | {f(d, 'time', 0)} "
                 f"| {'usable' if r.usable else ', '.join(r.flags)} "
                 f"| {'; '.join(r.reasons) or '-'} |")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


def _plot(path, results, choice):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 2, figsize=(13, 8))
    for col, axis, xl, scale in ((0, "loss", "packet loss", 100),
                                 (1, "latency", "mean latency (s)", 0.001)):
        rs = sorted((r for r in results if r.level.axis == axis), key=lambda r: r.level.x)
        if not rs:
            continue
        xs = [r.level.x * scale for r in rs]
        for row, k, yl in ((0, "dup", "duplicated sectors"), (1, "time", "mission time (s)")):
            ax = axes[row][col]
            for a in rs[0].by_arch:
                ax.errorbar(xs, [r.by_arch[a][f"{k}_mean"] for r in rs],
                            yerr=[r.by_arch[a][f"{k}_sd"] for r in rs],
                            marker="o", capsize=3, label=a)
            for r, x in zip(rs, xs):
                if not r.usable:
                    ax.axvspan(x - 0.4 * (xs[1] - xs[0] if len(xs) > 1 else 1),
                               x + 0.4 * (xs[1] - xs[0] if len(xs) > 1 else 1),
                               color="grey", alpha=0.12, lw=0)
            if axis == "loss":
                for role, c in (("moderate", "orange"), ("severe", "red")):
                    ch = choice.get(role)
                    if ch is not None:
                        ax.axvline(ch.level.x * scale, color=c, ls="--", label=role)
            if axis == "latency":
                ax.set_xscale("symlog", linthresh=1)
            ax.set_xlabel(xl + (" (%)" if axis == "loss" else ""))
            ax.set_ylabel(yl)
            ax.grid(alpha=0.3)
            ax.legend(fontsize=8)
    fig.suptitle("Communication calibration - grey = level rejected "
                 "(useless / too weak / trivial / flat)")
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def _write_final(path, choice, ladder_path):
    import yaml
    out = {"_comment": ("Final network profiles chosen by scripts/calibrate_comms.py "
                        f"from {os.path.relpath(ladder_path, ROOT)}. Frozen by "
                        "Phase 17.4 - do not edit by hand; re-run the calibration.")}
    for role in ("nominal", "moderate", "severe"):
        r = choice.get(role)
        if r is None:
            continue
        p = r.level.profile
        out[f"final_{role}"] = {
            "calibrated_from": r.level.name,
            "latency_ms_mean": p.latency_ms_mean,
            "latency_ms_jitter": p.latency_ms_jitter,
            "packet_loss_probability": p.packet_loss_probability}
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(out, f, sort_keys=False)


if __name__ == "__main__":
    sys.exit(main())
