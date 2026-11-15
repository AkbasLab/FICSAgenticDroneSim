"""Phase 19.1-19.2: paired comparisons and interaction models.

    python scripts/phase19_extract.py results/main_v1 results/main_v2
    python scripts/phase19_analysis.py

Reads paper/figure_data/phase19_runs.csv; writes paper/figure_data/phase19.json.

Conventions (stated in docs/ANALYSIS_phase19.md):

* Pairs are formed within a design only: same seed, team size, network and
  failure condition, so both runs flew the same mission. D (main_v1) and DV2
  (main_v2) never share seeds, so they are compared through their paired
  difference from C on their own seeds ("difference in differences"), with C
  as the anchor; A, B and C are checked to be stable across the two seed sets.
* Confidence intervals are 95% percentile bootstraps that resample **seeds**
  (20 clusters), not individual pairs: under common random numbers one seed
  appears in all 16 cells of an architecture, so pairs from one seed are not
  independent. This is more conservative than resampling pairs.
* Effect sizes: Cohen's d_z (mean / sd of the paired difference) and the
  probability of superiority P(delta > 0) + 0.5 P(delta = 0). For success, the
  risk difference with McNemar's discordant counts.
* Mission time is the time at which the run ended, for every run. It is not
  completion time; that is reported separately for pairs where both succeeded.
"""

import csv
import json
import math
import os
import random
import sys
from collections import defaultdict

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "paper", "figure_data")
NETS = ["final_nominal", "final_moderate", "final_severe", "final_partitioned"]
B = 4000
RNG_SEED = 20261114

# The one main_v2 run whose logs predate its X1 re-run: it succeeded on re-run
# (factorial_main_v2.json, cell DV2/n2/nominal/one_failure = 20/20), but its
# result directory was not part of the analysed archive. It counts for success,
# and is absent from every continuous metric.
RERUN_SUCCESS = {"main_v2_DV2_n2_final_nominal_one_failure_s25294"}


def load():
    rows = []
    with open(os.path.join(DATA, "phase19_runs.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            for k in ("team_size", "seed"):
                r[k] = int(r[k])
            r["success"] = r["success"] == "True" or r["experiment_id"] in RERUN_SUCCESS
            for k in ("score", "time_s", "coverage", "safe_return", "msgs_sent",
                      "recovery_start_s", "recovery_sweep_s", "dup"):
                r[k] = float(r[k]) if r.get(k) not in (None, "") else None
            rows.append(r)
    return rows


def key(r):
    return (r["team_size"], r["network"], r["failure"], r["seed"])


def pairs(rows, design, x, y, metric, where=lambda r: True):
    a = {key(r): r for r in rows if r["design"] == design and r["arch"] == x and where(r)}
    b = {key(r): r for r in rows if r["design"] == design and r["arch"] == y and where(r)}
    out = []
    for k in sorted(set(a) & set(b)):
        va, vb = a[k][metric], b[k][metric]
        if va is None or vb is None:
            continue
        out.append((k[3], float(va) - float(vb), a[k], b[k]))
    return out


def cluster_boot(seed_deltas, stat=np.mean, b=B, rng_seed=RNG_SEED):
    """seed_deltas: {seed: [delta, ...]}; resample seeds with replacement."""
    seeds = sorted(seed_deltas)
    rng = random.Random(rng_seed)
    vals = []
    for _ in range(b):
        pick = [seeds[rng.randrange(len(seeds))] for _ in seeds]
        xs = [d for s in pick for d in seed_deltas[s]]
        vals.append(float(stat(np.array(xs))))
    vals.sort()
    return [round(vals[int(0.025 * b)], 4), round(vals[int(0.975 * b) - 1], 4)]


def mcnemar(b_, c_):
    n = b_ + c_
    if n == 0:
        return 1.0
    k = min(b_, c_)
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def summarize(prs, binary=False):
    if not prs:
        return None
    d = np.array([p[1] for p in prs])
    by_seed = defaultdict(list)
    for s, v, _, _ in prs:
        by_seed[s].append(v)
    sd = float(d.std(ddof=1)) if len(d) > 1 else 0.0
    out = {"n_pairs": int(len(d)), "n_seeds": len(by_seed),
           "mean": round(float(d.mean()), 4), "median": round(float(np.median(d)), 4),
           "ci95_mean": cluster_boot(by_seed),
           "quantiles": {q: round(float(np.quantile(d, q / 100)), 3)
                         for q in (10, 25, 50, 75, 90)},
           "share_better": round(float((d > 0).mean()), 4),
           "share_equal": round(float((d == 0).mean()), 4),
           "share_worse": round(float((d < 0).mean()), 4),
           "prob_superiority": round(float((d > 0).mean() + 0.5 * (d == 0).mean()), 4),
           "cohen_dz": None if sd == 0 else round(float(d.mean() / sd), 3),
           "per_seed_mean": {int(s): round(float(np.mean(v)), 4)
                             for s, v in sorted(by_seed.items())}}
    if binary:
        xo = int(sum(1 for v in d if v > 0))
        yo = int(sum(1 for v in d if v < 0))
        out.update(x_only=xo, y_only=yo, mcnemar_p=mcnemar(xo, yo))
    return out


def compare(rows, design, x, y):
    res = {}
    for metric, binary in (("success", True), ("score", False), ("time_s", False)):
        m = "success_num" if metric == "success" else metric
        res[metric] = summarize(pairs(rows, design, x, y, m), binary)
    # completion time where both succeeded
    both = [p for p in pairs(rows, design, x, y, "time_s")
            if p[2]["success"] and p[3]["success"]]
    res["completion_time_both_succeeded"] = summarize(both)
    res["by_network"] = {n: summarize(pairs(rows, design, x, y, "success_num",
                                            lambda r, n=n: r["network"] == n), True)
                         for n in NETS}
    res["by_team"] = {t: summarize(pairs(rows, design, x, y, "success_num",
                                         lambda r, t=t: r["team_size"] == t), True)
                      for t in (2, 4)}
    res["by_failure"] = {f: summarize(pairs(rows, design, x, y, "success_num",
                                            lambda r, f=f: r["failure"] == f), True)
                         for f in ("none", "one_failure")}
    return res


def did(rows, metric="success_num"):
    """(D - C on main_v1) vs (DV2 - C on main_v2): each design's paired
    differences averaged per seed, then the two independent sets of seeds
    resampled separately."""
    out = {}
    for name, design, agent in (("v1", "main_v1", "D"), ("v2", "main_v2", "DV2")):
        prs = pairs(rows, design, agent, "C", metric)
        bs = defaultdict(list)
        for s, v, _, _ in prs:
            bs[s].append(v)
        out[name] = {s: float(np.mean(v)) for s, v in bs.items()}
    rng = random.Random(RNG_SEED)
    s1, s2 = sorted(out["v1"]), sorted(out["v2"])
    point = np.mean(list(out["v2"].values())) - np.mean(list(out["v1"].values()))
    vals = []
    for _ in range(B):
        a = np.mean([out["v1"][s1[rng.randrange(len(s1))]] for _ in s1])
        b = np.mean([out["v2"][s2[rng.randrange(len(s2))]] for _ in s2])
        vals.append(b - a)
    vals.sort()
    return {"metric": metric, "dv2_minus_d_relative_to_c": round(float(point), 4),
            "ci95": [round(vals[int(0.025 * B)], 4), round(vals[int(0.975 * B) - 1], 4)]}


def anchor_stability(rows):
    """A, B, C on seeds 1-20 vs 21-40: unpaired difference in means."""
    out = {}
    for arch in ("A", "B", "C"):
        for metric in ("success_num", "score", "time_s"):
            v1 = [r[metric] for r in rows if r["design"] == "main_v1" and r["arch"] == arch
                  and r[metric] is not None]
            v2 = [r[metric] for r in rows if r["design"] == "main_v2" and r["arch"] == arch
                  and r[metric] is not None]
            out[f"{arch}_{metric}"] = {"main_v1": round(float(np.mean(v1)), 4),
                                       "main_v2": round(float(np.mean(v2)), 4)}
    return out


def degradation(rows, design, archs, metric="success_num"):
    """Per architecture: paired (condition - nominal) within seed, team size and
    failure condition; and between architectures: the difference of those
    differences, paired by seed. This is the 'does the degradation curve
    differ' question, without a model."""
    def deltas(arch, cond):
        a = {(r["team_size"], r["failure"], r["seed"]): r for r in rows
             if r["design"] == design and r["arch"] == arch and r["network"] == cond}
        n = {(r["team_size"], r["failure"], r["seed"]): r for r in rows
             if r["design"] == design and r["arch"] == arch and r["network"] == "final_nominal"}
        return {k: a[k][metric] - n[k][metric] for k in set(a) & set(n)
                if a[k][metric] is not None and n[k][metric] is not None}
    out = {}
    for cond in NETS[1:]:
        per = {a: deltas(a, cond) for a in archs}
        out[cond] = {"drop": {}, "difference_vs": {}}
        for a, dd in per.items():
            bs = defaultdict(list)
            for k, v in dd.items():
                bs[k[2]].append(v)
            out[cond]["drop"][a] = {"mean": round(float(np.mean(list(dd.values()))), 4),
                                    "ci95": cluster_boot(bs)}
        for a in archs:
            for b_ in archs:
                if a >= b_:
                    continue
                common = set(per[a]) & set(per[b_])
                bs = defaultdict(list)
                for k in common:
                    bs[k[2]].append(per[a][k] - per[b_][k])
                vals = [v for vv in bs.values() for v in vv]
                out[cond]["difference_vs"][f"{a}-{b_}"] = {
                    "mean": round(float(np.mean(vals)), 4), "ci95": cluster_boot(bs)}
    return out


def interaction_models(rows, design):
    import pandas as pd
    import statsmodels.formula.api as smf
    # B is excluded: it never communicates, so its outcome is identical in
    # every network condition by construction and its interaction terms carry
    # no information (they only make the Wald covariance singular).
    df = pd.DataFrame([r for r in rows if r["design"] == design and r["arch"] != "B"])
    df["team"] = df["team_size"].astype(str)
    out = {}
    for y in ("success_num", "score", "time_s"):
        d = df.dropna(subset=[y])
        f = f"{y} ~ C(arch, Treatment('C')) * C(network, Treatment('final_nominal')) * C(team) + C(failure)"
        m = smf.ols(f, data=d).fit(cov_type="cluster", cov_kwds={"groups": d["seed"]})
        names = m.params.index
        def joint(pred):
            idx = [i for i, n in enumerate(names) if pred(n)]
            if not idx:
                return None
            R = np.zeros((len(idx), len(names)))
            for j, i in enumerate(idx):
                R[j, i] = 1
            w = m.wald_test(R, scalar=True)
            return {"terms": len(idx), "stat": round(float(w.statistic), 3),
                    "p": float(w.pvalue)}
        out[y] = {
            "n": int(m.nobs), "r2": round(float(m.rsquared), 3),
            "arch_x_network": joint(lambda n: "C(arch" in n and "C(network" in n
                                    and "C(team" not in n),
            "arch_x_network_x_team": joint(lambda n: "C(arch" in n and "C(network" in n
                                           and "C(team" in n),
            "arch_x_team": joint(lambda n: "C(arch" in n and "C(team" in n
                                 and "C(network" not in n),
            "failure": {"coef": round(float(m.params[[n for n in names if "failure" in n][0]]), 4),
                        "p": float(m.pvalues[[n for n in names if "failure" in n][0]])},
            "note": "OLS (linear probability model for success), 3-way interaction "
                    "architecture x network x team size plus failure; SEs clustered "
                    "by seed (20 clusters); reference: C, nominal, 2 UAVs; B excluded."}
    return out


def main():
    rows = load()
    for r in rows:
        r["success_num"] = 1.0 if r["success"] else 0.0
    out = {"conventions": __doc__.strip().splitlines()[6:],
           "paired": {
               "main_v1": {f"{x}_vs_{y}": compare(rows, "main_v1", x, y)
                           for x, y in (("D", "C"), ("D", "A"), ("C", "A"), ("C", "B"))},
               "main_v2": {f"{x}_vs_{y}": compare(rows, "main_v2", x, y)
                           for x, y in (("DV2", "C"), ("DV2", "A"), ("C", "A"), ("C", "B"))}},
           "did_dv2_vs_d": {m: did(rows, m) for m in ("success_num", "score", "time_s")},
           "anchor_stability": anchor_stability(rows),
           "degradation": {"main_v1": {m: degradation(rows, "main_v1", ["A", "C", "D"], m)
                                       for m in ("success_num", "score", "time_s")},
                           "main_v2": {m: degradation(rows, "main_v2", ["A", "C", "DV2"], m)
                                       for m in ("success_num", "score", "time_s")}},
           "models": {d: interaction_models(rows, d) for d in ("main_v1", "main_v2")}}
    path = os.path.join(DATA, "phase19.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, default=float)
    print(f"wrote {path}")
    for design, comps in out["paired"].items():
        for name, c in comps.items():
            s, sc, t = c["success"], c["score"], c["time_s"]
            print(f"{design} {name:10s} success d={s['mean']:+.3f} {s['ci95_mean']} "
                  f"McN p={s['mcnemar_p']:.2g} | score d={sc['mean']:+.3f} "
                  f"med {sc['median']:+.3f} {sc['ci95_mean']} dz={sc['cohen_dz']} "
                  f"PS={sc['prob_superiority']} | time d={t['mean']:+.1f} "
                  f"med {t['median']:+.1f} {t['ci95_mean']} dz={t['cohen_dz']}")
    print("DiD:", json.dumps(out["did_dv2_vs_d"]))
    for d, ms in out["models"].items():
        for y, m in ms.items():
            print(d, y, "AxN", m["arch_x_network"], "AxNxT", m["arch_x_network_x_team"],
                  "AxT", m["arch_x_team"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
