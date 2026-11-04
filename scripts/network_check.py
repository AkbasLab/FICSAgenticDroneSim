#!/usr/bin/env python3
"""Phase 10's statistical verification of the network model (AUV-10, 10.6).

    python scripts/network_check.py                    # the four conditions and the two stress networks, seeds 1-20
    python scripts/network_check.py --seeds 17 --block t

Thousands of heartbeats through the real bus per condition and seed, no
flight (`experiments/network_check.py` says how each check is made). The two
statistical checks -- loss inside its 99 % interval, latency by a KS test at
1 % -- reject a true model one time in a hundred by chance, so each holds for
a condition when no more than MAX_REJECTIONS of its seeds reject (with 20
seeds, three or more rejections happen by chance about once in a thousand).
Every other check -- the rate limit, partitions, expiry, seeds -- is exact,
and must hold on every seed.

Outputs, under phases/phase-10-degraded-communications/results/ by default:

    network-check-<stamp>[-<block>].jsonl   a header (the manifests, the verdict); one row per condition and
                                            seed, and per stress network and seed
    network-check-<stamp>[-<block>].md      the table and the verdict

Exit code 0 only if every check held.
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

from agentic_uav.experiments.conditions import CONDITIONS, load_network, network_path  # noqa: E402
from agentic_uav.experiments.network_check import (  # noqa: E402
    BURST_PERIOD_S,
    BURST_S,
    STEADY_PERIOD_S,
    STEADY_S,
    check_condition,
    check_stress,
    narrow_model,
    slow_model,
)
from agentic_uav.experiments.provenance import provenance  # noqa: E402
from agentic_uav.experiments.search_relay import EXIT_SEEDS  # noqa: E402

DEFAULT_OUT = os.path.join(REPO, "phases", "phase-10-degraded-communications", "results")
STATISTICAL = ("loss", "latency")
EXACT = ("rate_limit", "partitions", "expiry", "seeds")
MAX_REJECTIONS = 2


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


def verdict(rows: list[dict], allowed: int = MAX_REJECTIONS) -> dict[str, dict]:
    """Per condition: each statistical check's rejections against `allowed`; each exact check on every seed."""
    out: dict[str, dict] = {}
    for c in dict.fromkeys(r["condition"] for r in rows):
        mine = [r for r in rows if r["condition"] == c]
        v: dict[str, dict] = {}
        for k in STATISTICAL:
            rejected = [r["seed"] for r in mine if not r[k]["ok"]]
            v[k] = {"rejected_seeds": rejected, "ok": len(rejected) <= allowed}
        for k in EXACT:
            failed = [r["seed"] for r in mine if not r[k]["ok"]]
            v[k] = {"failed_seeds": failed, "ok": not failed}
        v["all"] = all(v[k]["ok"] for k in STATISTICAL + EXACT)
        out[c] = v
    return out


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
    wall = time.perf_counter()
    models = {c: load_network(c) for c in CONDITIONS}
    rows = [{"kind": "condition", **check_condition(models[c], s)} for c in CONDITIONS for s in args.seeds]
    stress = [{"kind": "stress", "seed": s, **check_stress(s)} for s in args.seeds]
    wall = time.perf_counter() - wall
    v = verdict(rows)
    stress_ok = all(r["all"] for r in stress)
    ok = all(x["all"] for x in v.values()) and stress_ok
    header = {"kind": "header", "t": started, "conditions": {c: models[c].as_json() for c in CONDITIONS},
              "manifests": {c: rel(network_path(c)) for c in CONDITIONS},
              "stress": {"slow": slow_model().as_json(), "narrow": narrow_model().as_json()},
              "streams": {"steady": {"period_s": STEADY_PERIOD_S, "duration_s": STEADY_S},
                          "burst": {"period_s": BURST_PERIOD_S, "duration_s": BURST_S}},
              "roster": ["Drone1", "Drone2", "Drone3", "Drone4"], "seeds": list(args.seeds),
              "max_rejections": MAX_REJECTIONS, "verdict": v, "stress_ok": stress_ok, "all": ok,
              "wall_s": round(wall, 2), "code": provenance()}

    lines = [f"# Network check — {len(args.seeds)} seed(s)", "",
             f"Run {started}, `scripts/network_check.py`, {wall:.1f} s wall. Heartbeats through the real bus, no flight: "
             f"each drone of four broadcasting every {STEADY_PERIOD_S:g} s for {STEADY_S:g} s (steady) and every "
             f"{BURST_PERIOD_S:g} s for {BURST_S:g} s (burst). Loss and latency are tests at 1 %: each holds when no "
             f"more than {MAX_REJECTIONS} of the seeds reject.", "",
             "| Condition | Loss (mean measured) | Latency KS (rejections) | Rate limit | Partitions | Expiry | Seeds | All |",
             "|---|---|---|---|---|---|---|---|"]
    for c in CONDITIONS:
        mine = [r for r in rows if r["condition"] == c]
        loss = sum(r["loss"]["rate"] for r in mine) / len(mine)
        x = v[c]
        lines.append(f"| {c} | {loss:.4f} vs {models[c].loss_probability:g}; {len(x['loss']['rejected_seeds'])} rejected "
                     f"| {len(x['latency']['rejected_seeds'])} rejected "
                     f"| {'yes' if x['rate_limit']['ok'] else '**no**'} ({sum(r['rate_limit']['refused'] for r in mine)} refused) "
                     f"| {'yes' if x['partitions']['ok'] else '**no**'} ({sum(r['partitions']['cut'] for r in mine)} cut) "
                     f"| {'yes' if x['expiry']['ok'] else '**no**'} ({sum(r['expiry']['expired'] for r in mine)} expired) "
                     f"| {'yes' if x['seeds']['ok'] else '**no**'} | {'yes' if x['all'] else '**no**'} |")
    expired = sum(r["slow"]["statuses"]["expired"] for r in stress)
    lines += ["", f"**Stress networks**: slow (3 ± 1 s) -- {expired} expired, none delivered late; narrow (500 B/s, four a "
                  f"second) -- latencies against the queue recomputed from sizes: "
                  f"{'held' if stress_ok else '**did not hold**'} on every seed.", "",
              f"**10.6: {'VERIFIED' if ok else 'NOT VERIFIED'}**", ""]
    problems = [f"{r['condition']} seed {r['seed']}, {k}: {p}" for r in rows for k in STATISTICAL + EXACT
                for p in r[k]["problems"]]
    if problems:
        lines += ["Rejections and problems:", ""] + [f"* {p}" for p in problems[:50]] + [""]

    os.makedirs(args.out, exist_ok=True)
    stem = f"network-check-{time.strftime('%Y%m%d-%H%M%S')}" + (f"-{args.block}" if args.block else "")
    with io.open(os.path.join(args.out, stem + ".jsonl"), "w", encoding="utf-8", newline="\n") as h:
        for row in [header] + rows + stress:
            h.write(json.dumps(row, default=str) + "\n")
    with io.open(os.path.join(args.out, stem + ".md"), "w", encoding="utf-8", newline="\n") as h:
        h.write("\n".join(lines))
    print("\n".join(lines))
    print(f"raw     : {os.path.join(args.out, stem + '.jsonl')}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
