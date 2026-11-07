"""Phase 17: which communication levels are meaningful -- docs/CONDITIONS.md's rule, applied (AUV-16 17.3).

    verdicts = judge(rows, delivery)      # rows: a scored batch (metrics.batch_metrics); delivery: run -> (got, lost)

The rule was committed (docs/CONDITIONS.md, version 1) before the sweep it judges was run. For a team size and a
degraded level, in each failure condition and for each architecture: the success rate, the median completion
(censored at the deadline) and its interquartile range, the mean continuity retention. A level is meaningful when
it is (1) not trivially easy, (2) not trivially hard, (3) distinguishable, and (4) communication is still useful.
The pilots' degraded level is the most degraded meaningful one of `severe`, then `moderate`.
"""

from __future__ import annotations

import statistics
from itertools import combinations
from typing import Any

NOMINAL = "nominal"
PREFERENCE = ("severe", "moderate")
EASY_SUCCESS, HARD_SUCCESS = 0.95, 0.05
SLOWER = 0.10                   # a median 10 % longer
SUCCESS_GAP, P3_GAP = 0.20, 0.05
USEFUL_DELIVERY = 0.50
VERSION = 1


def quartiles(xs: list[float]) -> tuple[float, float, float]:
    q1, q2, q3 = statistics.quantiles(xs, n=4, method="inclusive") if len(xs) > 1 else (xs[0],) * 3
    return q1, q2, q3


def arm_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    done = [r["values"]["P2.completion_s"] for r in rows]
    p3 = [r["values"]["P3.continuity_retention"] for r in rows if "P3.continuity_retention" in r["values"]]
    q1, med, q3 = quartiles(done)
    return {"runs": len(rows), "success": sum(bool(r["values"]["P1.success"]) for r in rows) / len(rows),
            "median_s": med, "iqr_s": [q1, q3], "p3": statistics.fmean(p3) if p3 else None}


def cells(rows: list[dict[str, Any]]) -> dict[tuple, dict[str, Any]]:
    """(team size, level, failure, architecture) -> that arm's statistics over its seeds."""
    groups: dict[tuple, list] = {}
    for r in rows:
        c = r["config"]
        groups.setdefault((c["team_size"], c["network"], c["failure"], c["architecture"]), []).append(r)
    return {k: arm_stats(v) for k, v in groups.items()}


def distinguishable(a: dict[str, Any], b: dict[str, Any]) -> list[str]:
    why = []
    if abs(a["success"] - b["success"]) >= SUCCESS_GAP - 1e-12:
        why.append(f"success {a['success']:.2f} vs {b['success']:.2f}")
    lo, hi = sorted((a["median_s"], b["median_s"]))
    apart = a["iqr_s"][1] < b["iqr_s"][0] or b["iqr_s"][1] < a["iqr_s"][0]
    if lo > 0 and (hi - lo) / lo >= SLOWER - 1e-12 and apart:
        why.append(f"median {a['median_s']:.1f} vs {b['median_s']:.1f} s, interquartile ranges apart")
    if a["p3"] is not None and b["p3"] is not None and abs(a["p3"] - b["p3"]) >= P3_GAP - 1e-12:
        why.append(f"retention {a['p3']:.3f} vs {b['p3']:.3f}")
    return why


def judge(rows: list[dict[str, Any]], delivery: dict[str, tuple[int, int]]) -> dict[str, Any]:
    stats = cells(rows)
    teams = sorted({k[0] for k in stats})
    out: dict[str, Any] = {"version": VERSION, "levels": {}, "pilot": {}, "phase18": {}}
    for n in teams:
        levels = sorted({k[1] for k in stats if k[0] == n and k[1] != NOMINAL})
        failures = sorted({k[2] for k in stats if k[0] == n})
        arms = sorted({k[3] for k in stats if k[0] == n})
        verdicts = {}
        for level in levels:
            easy_why, hard, signal = [], True, []
            for f in failures:
                for a in arms:
                    s, ref = stats.get((n, level, f, a)), stats.get((n, NOMINAL, f, a))
                    if s is None:
                        continue
                    if s["success"] < EASY_SUCCESS:
                        easy_why.append(f"{a}, {f}: success {s['success']:.2f}")
                    elif ref is not None and s["median_s"] >= (1 + SLOWER) * ref["median_s"] - 1e-9:
                        easy_why.append(f"{a}, {f}: median {s['median_s']:.1f} s against {ref['median_s']:.1f} s nominal")
                    if s["success"] > HARD_SUCCESS:
                        hard = False
                for a, b in combinations(arms, 2):
                    sa, sb = stats.get((n, level, f, a)), stats.get((n, level, f, b))
                    if sa and sb:
                        signal += [f"{f}, {a} vs {b}: {w}" for w in distinguishable(sa, sb)]
            runs = [r["run_id"] for r in rows if r["config"]["team_size"] == n and r["config"]["network"] == level]
            got = sum(delivery[r][0] for r in runs)
            lost = sum(delivery[r][1] for r in runs)
            rate = got / (got + lost) if got + lost else 0.0
            checks = {"not_trivially_easy": bool(easy_why), "not_trivially_hard": not hard,
                      "distinguishable": bool(signal), "communication_useful": rate >= USEFUL_DELIVERY}
            verdicts[level] = {"meaningful": all(checks.values()), "checks": checks, "delivery_rate": round(rate, 4),
                               "why_not_easy": easy_why[:12], "signal": signal[:20]}
        out["levels"][str(n)] = verdicts
        chosen = next((lv for lv in PREFERENCE if verdicts.get(lv, {}).get("meaningful")), None)
        out["pilot"][str(n)] = chosen
        out["phase18"][str(n)] = [NOMINAL] + [lv for lv, v in verdicts.items() if v["meaningful"]]
    out["stats"] = {f"{k[0]}|{k[1]}|{k[2]}|{k[3]}": v for k, v in sorted(stats.items())}
    return out
