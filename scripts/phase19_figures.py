"""Phase 19.3: degradation curves and the failure taxonomy, in one figure.

    python scripts/phase19_figures.py

Reads paper/figure_data/phase19_runs.csv, phase19_failures.csv and
results/calibration/calibration.csv; writes
paper/figures/fig12_degradation.{pdf,png,svg}.

Panels
  (a,b) mission score vs packet loss, 2 and 4 UAVs (partition shown at right)
  (c)   time to mission end vs link latency - from the Phase 17 calibration
        sweep (4 UAVs, B/C/scripted D, 10 seeds): the factorial held latency at
        150 ms, so this is the only latency evidence, and it is labelled so
  (d)   continuity retention: score(condition) / score(nominal), same seed
  (e)   recovery time after a failure: until a teammate flies toward the lost
        drone's unfinished sector
  (f)   communication overhead: messages sent per run vs team size
  (g)   primary cause of every failed mission (B omitted: it never
        reallocates work, so every one of its failures is by design)

D is main_v1 (seeds 1-20), DV2 main_v2 (seeds 21-40); A and C are shown from
main_v2 and were stable across the two seed sets (docs/ANALYSIS_phase19.md).
Error bars are 95% bootstrap intervals over seeds.
"""

import csv
import os
import random
from collections import Counter, defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "paper", "figure_data")
FIGS = os.path.join(ROOT, "paper", "figures")
LOSS = {"final_nominal": 0, "final_moderate": 10, "final_severe": 50}
NETS = ["final_nominal", "final_moderate", "final_severe", "final_partitioned"]
SERIES = [("A", "main_v2", "A centralized", "#CC79A7", "o"),
          ("B", "main_v2", "B independent", "#555555", "x"),
          ("C", "main_v2", "C deterministic", "#0072B2", "s"),
          ("D", "main_v1", "D agentic (main_v1)", "#E69F00", "v"),
          ("DV2", "main_v2", "DV2 agentic + phase checks", "#009E73", "^")]
plt.rcParams.update({"font.family": "serif", "font.size": 7, "axes.titlesize": 7.5,
                     "axes.spines.top": False, "axes.spines.right": False})


def load(name):
    with open(os.path.join(DATA, name), encoding="utf-8") as f:
        return list(csv.DictReader(f))


def fnum(x):
    return float(x) if x not in (None, "") else None


def boot(by_seed, b=2000, seed=7):
    seeds = sorted(by_seed)
    if not seeds:
        return np.nan, np.nan, np.nan
    rng = random.Random(seed)
    vals = []
    for _ in range(b):
        xs = [v for s in (seeds[rng.randrange(len(seeds))] for _ in seeds) for v in by_seed[s]]
        vals.append(np.mean(xs))
    allv = [v for vv in by_seed.values() for v in vv]
    return float(np.mean(allv)), float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def main():
    runs = load("phase19_runs.csv")
    fails = load("phase19_failures.csv")
    sel = lambda a, d: [r for r in runs if r["arch"] == a and r["design"] == d
                        and r["has_logs"] == "True"]
    fig = plt.figure(figsize=(7.16, 6.0))
    gs = fig.add_gridspec(3, 3, hspace=0.8, wspace=0.5)

    # (a,b) score vs loss
    for col, n in enumerate((2, 4)):
        ax = fig.add_subplot(gs[0, col])
        for a, d, lab, c, m in SERIES:
            xs, ys, lo, hi = [], [], [], []
            for net in NETS:
                bs = defaultdict(list)
                for r in sel(a, d):
                    if int(r["team_size"]) == n and r["network"] == net and fnum(r["score"]) is not None:
                        bs[r["seed"]].append(float(r["score"]))
                mu, l, h = boot(bs)
                xs.append(LOSS.get(net, 65))
                ys.append(mu), lo.append(mu - l), hi.append(h - mu)
            ax.errorbar(xs[:3], ys[:3], yerr=[lo[:3], hi[:3]], color=c, marker=m, ms=3,
                        lw=1, capsize=1.5, label=lab)
            ax.errorbar([xs[3]], [ys[3]], yerr=[[lo[3]], [hi[3]]], color=c, marker=m, ms=3,
                        capsize=1.5, ls="none")
        ax.set_xticks([0, 10, 50, 65])
        ax.set_xticklabels(["0", "10", "50", "part."])
        ax.set_xlabel("packet loss (%)")
        ax.set_ylabel("mission score")
        ax.set_ylim(0.4, 1.04)
        ax.set_title(f"(a{col + 1}) score vs loss, {n} UAVs")
    fig.axes[1].legend(fontsize=5.6, frameon=False, loc="lower left")

    # (c) time vs latency, calibration sweep
    ax = fig.add_subplot(gs[0, 2])
    cal = [r for r in load_cal() if r["axis"] == "latency" or r["level"] == "loss05"]
    for a, lab, c, m in (("B", "B", "#555555", "x"), ("C", "C", "#0072B2", "s"),
                         ("D", "D (scripted)", "#E69F00", "v")):
        pts = sorted((float(r["latency_ms"]) / 1000, float(r["time_mean"]), float(r["time_sd"]))
                     for r in cal if r["architecture"] == a)
        ax.errorbar([p[0] for p in pts], [p[1] for p in pts], yerr=[p[2] for p in pts],
                    color=c, marker=m, ms=3, lw=1, capsize=1.5, label=lab)
    ax.set_xscale("log")
    ax.set_xlabel("mean link latency (s)")
    ax.set_ylabel("mission time (s)")
    ax.set_title("(c) time vs latency\n(Phase 17 sweep, 4 UAVs, 1 failure)")
    ax.legend(fontsize=5.6, frameon=False)

    # (d) continuity retention
    ax = fig.add_subplot(gs[1, 0])
    for i, (a, d, lab, c, m) in enumerate(SERIES):
        rs = sel(a, d)
        nom = {(r["team_size"], r["failure"], r["seed"]): fnum(r["score"]) for r in rs
               if r["network"] == "final_nominal"}
        ys, lo, hi = [], [], []
        for net in NETS:
            bs = defaultdict(list)
            for r in rs:
                k = (r["team_size"], r["failure"], r["seed"])
                if r["network"] == net and nom.get(k) and fnum(r["score"]) is not None:
                    bs[r["seed"]].append(float(r["score"]) / nom[k])
            mu, l, h = boot(bs)
            ys.append(mu), lo.append(mu - l), hi.append(h - mu)
        x = np.arange(4) + (i - 2) * 0.08
        ax.errorbar(x, ys, yerr=[lo, hi], color=c, marker=m, ms=3, lw=1, capsize=1.5)
    ax.axhline(1, color="#999", lw=0.6, ls=":")
    ax.set_xticks(range(4))
    ax.set_xticklabels(["nom.", "mod.", "sev.", "part."])
    ax.set_ylabel("score / score(nominal)")
    ax.set_title("(d) continuity retention")

    # (e) recovery time
    ax = fig.add_subplot(gs[1, 1])
    data, labels, colors, rec = [], [], [], []
    for a, d, lab, c, m in SERIES:
        if a == "B":
            continue
        rs = [r for r in sel(a, d) if r["failure"] == "one_failure" and r["orphan"]]
        v = [float(r["recovery_start_s"]) for r in rs if r["recovery_start_s"]]
        data.append(v), labels.append(a), colors.append(c)
        rec.append((len(v), len(rs)))
    bp = ax.boxplot(data, patch_artist=True, widths=0.55, showfliers=True,
                    flierprops={"ms": 2})
    for patch, c in zip(bp["boxes"], colors):
        patch.set_facecolor(c), patch.set_alpha(0.55)
    ax.set_xticks(range(1, len(labels) + 1))
    ax.set_xticklabels([f"{l}\n{k}/{n}" for l, (k, n) in zip(labels, rec)], fontsize=5.5)
    ax.set_ylabel("time to recovery (s)")
    ax.set_title("(e) recovery time (recovered / orphaned)")

    # (f) communication overhead
    ax = fig.add_subplot(gs[1, 2])
    for a, d, lab, c, m in SERIES:
        ys, lo, hi = [], [], []
        for n in (2, 4):
            bs = defaultdict(list)
            for r in sel(a, d):
                if int(r["team_size"]) == n and r["msgs_sent"]:
                    bs[r["seed"]].append(float(r["msgs_sent"]))
            mu, l, h = boot(bs)
            ys.append(mu), lo.append(mu - l), hi.append(h - mu)
        ax.errorbar([2, 4], ys, yerr=[lo, hi], color=c, marker=m, ms=3, lw=1, capsize=1.5)
    ax.set_xticks([2, 4])
    ax.set_xlabel("team size (UAVs)")
    ax.set_ylabel("messages sent per run")
    ax.set_title("(f) communication overhead")

    # (g) failure taxonomy
    ax = fig.add_subplot(gs[2, :])
    order = ["LLM_MISSION_MISINTERPRETATION", "LLM_INVALID_ACTION", "STALE_INFORMATION",
             "TASK_NOT_REALLOCATED", "COMMUNICATION_PARTITION", "EVALUATION_ARTEFACT"]
    pal = ["#E69F00", "#F0C060", "#56B4E9", "#CC79A7", "#999999", "#DDDDDD"]
    rowsets = [("A", "main_v1", "A (v1)"), ("C", "main_v1", "C (v1)"), ("D", "main_v1", "D (v1)"),
               ("A", "main_v2", "A (v2)"), ("C", "main_v2", "C (v2)"), ("DV2", "main_v2", "DV2 (v2)")]
    left = np.zeros(len(rowsets))
    for cls, col in zip(order, pal):
        vals = np.array([sum(1 for f in fails if f["arch"] == a and f["design"] == d
                             and f["primary"] == cls) for a, d, _ in rowsets])
        ax.barh(range(len(rowsets)), vals, left=left, color=col, label=cls.replace("_", " ").lower())
        left += vals
    for i, v in enumerate(left):
        ax.text(v * 1.12 + 0.3, i, f"{int(v)} of 320", va="center", fontsize=6)
    ax.set_yticks(range(len(rowsets)))
    ax.set_yticklabels([r[2] for r in rowsets])
    ax.invert_yaxis()
    ax.set_xscale("symlog", linthresh=10)
    ax.set_xlabel("failed missions (symlog scale)")
    ax.set_title("(g) primary cause of failed missions (classified from the decision traces)")
    ax.set_xlim(0, 600)
    ax.legend(fontsize=5.6, frameon=False, ncol=3, loc="upper center",
              bbox_to_anchor=(0.5, -0.32))

    os.makedirs(FIGS, exist_ok=True)
    for ext in ("pdf", "png", "svg"):
        fig.savefig(os.path.join(FIGS, f"fig12_degradation.{ext}"), dpi=300,
                    bbox_inches="tight")
    print("wrote paper/figures/fig12_degradation.{pdf,png,svg}")


def load_cal():
    with open(os.path.join(ROOT, "results", "calibration", "calibration.csv"),
              encoding="utf-8") as f:
        return list(csv.DictReader(f))


if __name__ == "__main__":
    main()
