"""Average repeated guardrail-benchmark runs per model, and test whether
temperature makes a difference.

    python scripts/summarise_benchmark_runs.py
    python scripts/summarise_benchmark_runs.py --dir results/benchmark --csv summary.csv

Reads every result file in the directory that has repeated runs (`--repeat`),
groups them by model, and prints for each model:

  * per temperature: mean +/- sd over its runs
  * all temperatures pooled: mean +/- sd over every run (e.g. 3 x 5 = 15)
  * a Kruskal-Wallis test across the temperatures for each metric

Kruskal-Wallis is used rather than ANOVA because TRA moves in steps of 1/12
and latency is skewed; neither is close to normal with five runs per group.
p < 0.05 means at least one temperature differs from the others.
"""

import argparse
import csv
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agentic_uav.experiments import guardrail_benchmark as gb

METRICS = [
    ("TRA (%)", "TRA (%)"),
    ("TRA model-only (%)", "TRA model-only (%)"),
    ("GBR (%)", "GBR (%)"),
    ("MVL (ms)", "MVL (ms)"),
    ("Model latency (ms)", "Mean model latency (ms)"),
    ("False rejection (%)", "False rejection rate (%)"),
    ("Unguarded breach (%)", "Unguarded breach rate (%)"),
]


def mean_sd(vals):
    vals = [v for v in vals if v is not None]
    if not vals:
        return None, None, 0
    m = sum(vals) / len(vals)
    sd = (math.sqrt(sum((v - m) ** 2 for v in vals) / (len(vals) - 1))
          if len(vals) > 1 else 0.0)
    return m, sd, len(vals)


def _chi2_sf(x, df):
    """Upper tail of the chi-square distribution (regularised gamma)."""
    if x <= 0:
        return 1.0
    a = df / 2.0
    # series for the lower incomplete gamma, fine for the small df used here
    term = total = 1.0 / a
    n = 1
    while term > 1e-15 * total and n < 1000:
        term *= (x / 2.0) / (a + n)
        total += term
        n += 1
    lower = total * math.exp(-x / 2.0 + a * math.log(x / 2.0) - math.lgamma(a))
    return max(0.0, min(1.0, 1.0 - lower))


def kruskal_wallis(groups):
    """H statistic and p-value, with the correction for ties. None if the
    test is undefined (fewer than two groups, or every value identical)."""
    groups = [[v for v in g if v is not None] for g in groups]
    groups = [g for g in groups if g]
    if len(groups) < 2:
        return None, None
    pooled = sorted((v, gi) for gi, g in enumerate(groups) for v in g)
    n = len(pooled)
    ranks = [0.0] * n
    ties = 0.0
    i = 0
    while i < n:
        j = i
        while j + 1 < n and pooled[j + 1][0] == pooled[i][0]:
            j += 1
        r = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[k] = r
        t = j - i + 1
        ties += t ** 3 - t
        i = j + 1
    correction = 1.0 - ties / (n ** 3 - n) if n > 1 else 0.0
    if correction == 0:
        return None, None                      # all values equal: no difference
    sums = [0.0] * len(groups)
    for (v, gi), r in zip(pooled, ranks):
        sums[gi] += r
    h = (12.0 / (n * (n + 1)) * sum(s * s / len(g) for s, g in zip(sums, groups))
         - 3.0 * (n + 1)) / correction
    return h, _chi2_sf(h, len(groups) - 1)


def load(directory):
    by_model = {}
    for r in gb.load_results(directory):
        if not r.get("per_run") or r["counters"].get("backend_errors"):
            continue
        m = r["model"]
        by_model.setdefault(m.get("model", "?"), []).append(r)
    for rows in by_model.values():
        rows.sort(key=lambda r: r["model"].get("temperature", 0.0))
    return by_model


def fmt(m, sd, key):
    if m is None:
        return "--"
    d = 4 if key == "MVL (ms)" else (0 if "latency" in key.lower() else 2)
    return f"{m:.{d}f} +/- {sd:.{d}f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.path.join(gb.ROOT, "results", "benchmark"))
    ap.add_argument("--csv", default=None, help="also write the summary here")
    args = ap.parse_args()

    by_model = load(args.dir)
    if not by_model:
        print(f"no finished repeated runs in {args.dir}")
        return 1

    rows_out = []
    for model, rows in sorted(by_model.items()):
        temps = [r["model"].get("temperature", 0.0) for r in rows]
        total = sum(len(r["per_run"]) for r in rows)
        print("=" * 78)
        print(f"{model}   temperatures {', '.join(f'{t:g}' for t in temps)}   "
              f"{total} runs in all")
        print("=" * 78)
        head = f"  {'metric':22s}" + "".join(f"{'T=' + format(t, 'g'):>20s}" for t in temps) \
            + f"{'all ' + str(total) + ' runs':>20s}{'K-W p':>9s}"
        print(head)
        for label, key in METRICS:
            groups = [[m.get(key) for m in r["per_run"]] for r in rows]
            cells = [mean_sd(g) for g in groups]
            pm, psd, _ = mean_sd([v for g in groups for v in g])
            h, p = kruskal_wallis(groups)
            ptxt = "--" if p is None else (f"{p:.3f}" + (" *" if p < 0.05 else ""))
            print(f"  {label:22s}" + "".join(f"{fmt(m, sd, label):>20s}" for m, sd, _ in cells)
                  + f"{fmt(pm, psd, label):>20s}{ptxt:>9s}")
            rows_out.append({
                "model": model, "metric": label,
                **{f"T={t:g} mean": c[0] for t, c in zip(temps, cells)},
                **{f"T={t:g} sd": c[1] for t, c in zip(temps, cells)},
                "pooled mean": pm, "pooled sd": psd, "runs": total,
                "kruskal_wallis_H": h, "p": p,
            })
        print()
    print("K-W p: Kruskal-Wallis across temperatures. * = p < 0.05 (temperature "
          "made a difference).\n'--' = undefined, e.g. every run gave the same value.")

    if args.csv:
        keys = sorted({k for r in rows_out for k in r},
                      key=lambda k: (k not in ("model", "metric"), k))
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            w.writerows(rows_out)
        print(f"\nwrote {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
