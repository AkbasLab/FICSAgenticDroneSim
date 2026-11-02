"""Per-run timelines, reconstructed from a result directory alone (Phase 17.2).

    from agentic_uav.experiments.timeline import load_run, build_timeline, plot
    run = load_run("results/pilot_v1/pilot_v1_C_n4_severe_s101")
    tl = build_timeline(run)          # plain data, testable without matplotlib
    plot(tl, "timeline.png")

Everything here is read from the files the experiment runner writes -
`events.jsonl`, `tracks.json`, `manifest.json`, `result.json` - and nothing
from the live objects. That is deliberate: if a timeline can be drawn from the
logs, the logs are complete enough to interpret the run, which is half of the
Phase 17 exit criterion. A panel that comes out empty when the run clearly did
something is a logging gap, and is reported as one.

The nine views 17.2 asks for:

  trajectories        tracks.json
  active task         BELIEF_UPDATED.task while the drone is working a task
  role                BELIEF_UPDATED.role
  messages over time  MESSAGE_SENT / RECEIVED / DROPPED
  comms outages       windows where every message addressed to a drone was lost
  task reallocations  a task starting to be worked by a different drone
  LLM decisions       LLM_CALLED (fallbacks marked)
  safety interventions GUARDIAN_INTERVENED
  mission progress    sectors finished (SKILL_COMPLETED sector_sweep) over time
"""

import json
import os
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

#: Objectives during which a drone is working its task. Outside these (taking
#: off, returning, landing, waiting to claim) the belief still names the last
#: task held, which would draw a drone as busy after it had finished.
WORKING = {"go_to_sector", "search_sector", "report", "relay", "inspect",
           "go_to_target", "search_region"}

#: Outage bins. A bin is an outage for a drone when at least one message was
#: addressed to it in the bin and none arrived.
OUTAGE_BIN_S = 10.0

#: LLM-policy hand-offs to deterministic code that are part of the design, not
#: failures: the model is not consulted before take-off, for landing, or when
#: there is nothing left to decide. Only the other causes are worth flagging.
BY_DESIGN_FALLBACKS = {"not_airborne_yet", "landing_is_deterministic",
                       "no_work_remaining", "standing_by"}
MESSAGE_BIN_S = 10.0


def load_run(directory) -> Dict[str, Any]:
    def read(name, default=None):
        path = os.path.join(directory, name)
        if not os.path.exists(path):
            return default
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    events = []
    path = os.path.join(directory, "events.jsonl")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            events = [json.loads(line) for line in f if line.strip()]
    return {"directory": directory, "events": events,
            "manifest": read("manifest.json", {}), "result": read("result.json"),
            "tracks": read("tracks.json", {})}


def _vehicles(run):
    team = run["manifest"].get("team") or []
    seen = sorted({e["vehicle"] for e in run["events"]
                   if e.get("vehicle", "") and str(e["vehicle"]).startswith("Drone")})
    return list(dict.fromkeys(list(team) + seen))


def build_timeline(run) -> Dict[str, Any]:
    ev = run["events"]
    vehicles = _vehicles(run)
    end = max([e["t"] for e in ev] + [0.0])
    faults = {e["vehicle"]: e["t"] for e in ev if e["type"] == "FAULT_INJECTED"}

    # --- per-step state: task, role, objective --------------------------------
    steps = defaultdict(list)                 # vid -> [(t, task, role, objective)]
    objective_at = {}
    for e in ev:
        if e["type"] == "DECISION_PROPOSED" and e.get("vehicle"):
            objective_at[(e["vehicle"], e["data"].get("step"))] = e["data"].get("objective")
    for e in ev:
        if e["type"] == "BELIEF_UPDATED" and e.get("vehicle"):
            d = e["data"]
            steps[e["vehicle"]].append(
                (e["t"], d.get("task"), d.get("role"),
                 objective_at.get((e["vehicle"], d.get("step")))))
    for v in steps:
        steps[v].sort(key=lambda s: s[0])

    def last_time(v):
        return min(faults.get(v, end), end) if v in faults else \
            (steps[v][-1][0] if steps.get(v) else end)

    def intervals(v, value_of):
        out, cur, since = [], None, None
        seq = steps.get(v, [])
        for t, task, role, obj in seq:
            val = value_of(task, role, obj)
            if val != cur:
                if cur is not None:
                    out.append((since, t, cur))
                cur, since = val, t
        if cur is not None:
            out.append((since, max(last_time(v), since), cur))
        return [(a, b, x) for a, b, x in out if x is not None]

    tasks = {v: intervals(v, lambda task, role, obj:
                          task if task and obj in WORKING else None)
             for v in vehicles}
    roles = {v: intervals(v, lambda task, role, obj: role) for v in vehicles}

    # --- reallocations and concurrent claims ----------------------------------
    # A drone taking up a task is a *reallocation* when the task was worked by
    # another drone before and nobody else is working it now (the usual case:
    # its holder failed or released it). It is a *concurrent claim* when another
    # drone is working the same task at that moment - two drones that did not
    # hear each other, which is how duplicate sweeps begin.
    reallocations, concurrent = [], []
    last_holder = {}
    starts = sorted((a, v, task) for v in vehicles for a, b, task in tasks[v])
    for t, v, task in starts:
        others = [u for u in vehicles if u != v and any(
            a <= t < b and x == task for a, b, x in tasks[u])]
        if others:
            concurrent.append({"t": t, "task": task, "vehicle": v, "with": others})
        elif task in last_holder and last_holder[task] != v:
            reallocations.append({"t": t, "task": task,
                                  "from": last_holder[task], "to": v})
        last_holder[task] = v
    released = [{"t": e["t"], "vehicle": e["vehicle"]} for e in ev
                if e["type"] == "TASK_RELEASED"]

    # --- messages and outages -------------------------------------------------
    nbins = int(end // MESSAGE_BIN_S) + 1
    msg = {k: [0] * nbins for k in ("sent", "received", "dropped")}
    drop_reasons = defaultdict(int)
    addressed = defaultdict(lambda: defaultdict(int))     # vid -> bin -> count
    arrived = defaultdict(lambda: defaultdict(int))
    for e in ev:
        b = min(int(e["t"] // MESSAGE_BIN_S), nbins - 1)
        if e["type"] == "MESSAGE_SENT":
            msg["sent"][b] += 1
            to = e["data"].get("to")
            if to:
                addressed[to][int(e["t"] // OUTAGE_BIN_S)] += 1
        elif e["type"] == "MESSAGE_RECEIVED":
            msg["received"][b] += 1
        elif e["type"] == "MESSAGE_DROPPED":
            msg["dropped"][b] += 1
            drop_reasons[e["data"].get("reason", "?")] += 1
    # A message counts towards the bin it was *sent* in, so a slow delivery is
    # not mistaken for an outage in the bin where it was sent.
    sent_at = {}
    for e in ev:
        if e["type"] == "MESSAGE_SENT":
            sent_at[(e["data"].get("message_id"), e["data"].get("to"))] = e["t"]
    for e in ev:
        if e["type"] == "MESSAGE_RECEIVED":
            t0 = sent_at.get((e["data"].get("message_id"), e["vehicle"]), e["t"])
            arrived[e["vehicle"]][int(t0 // OUTAGE_BIN_S)] += 1
    outages = {}
    for v in vehicles:
        windows = []
        stop = faults.get(v)
        for b in sorted(addressed[v]):
            t0 = b * OUTAGE_BIN_S
            if stop is not None and t0 >= stop:
                continue                       # a dead drone is not "cut off"
            if addressed[v][b] > 0 and arrived[v].get(b, 0) == 0:
                windows.append((t0, t0 + OUTAGE_BIN_S))
        merged = []
        for a, b in windows:
            if merged and abs(merged[-1][1] - a) < 1e-9:
                merged[-1] = (merged[-1][0], b)
            else:
                merged.append((a, b))
        outages[v] = merged
    # Delivered fraction of the messages addressed to each drone, per window:
    # an outage is the extreme case (0), but heavy partial loss matters too.
    delivery = {v: [(b * OUTAGE_BIN_S, addressed[v][b],
                     arrived[v].get(b, 0) / addressed[v][b])
                    for b in sorted(addressed[v]) if addressed[v][b] > 0
                    and (faults.get(v) is None or b * OUTAGE_BIN_S < faults[v])]
                for v in vehicles}

    # --- LLM, guardian, progress ---------------------------------------------
    llm = [{"t": e["t"], "vehicle": e["vehicle"], "tool": e["data"].get("tool"),
            "fallback": bool(e["data"].get("used_fallback")),
            "by_design": e["data"].get("fallback_cause") in BY_DESIGN_FALLBACKS,
            "cause": e["data"].get("fallback_cause")}
           for e in ev if e["type"] == "LLM_CALLED"]
    guardian = [{"t": e["t"], "vehicle": e["vehicle"],
                 "outcome": e["data"].get("outcome"),
                 "checks": e["data"].get("failed_checks", [])}
                for e in ev if e["type"] == "GUARDIAN_INTERVENED"]
    sweeps = sorted(({"t": e["t"], "vehicle": e["vehicle"],
                      "sector": e["data"].get("sector")}
                     for e in ev if e["type"] == "SKILL_COMPLETED"
                     and e["data"].get("skill") == "sector_sweep"),
                    key=lambda s: s["t"])
    progress, seen = [], set()
    for s in sweeps:
        dup = s["sector"] in seen
        seen.add(s["sector"])
        progress.append({**s, "distinct": len(seen), "duplicate": dup})
    targets = {}
    for e in ev:
        if e["type"] == "TARGET_FOUND" and e["data"].get("target_id"):
            targets.setdefault(e["data"]["target_id"], e["t"])

    return {
        "run": os.path.basename(run["directory"].rstrip("/\\")),
        "manifest": run["manifest"], "result": run["result"] or {},
        "vehicles": vehicles, "end": end, "faults": faults,
        "tracks": run["tracks"], "tasks": tasks, "roles": roles,
        "reallocations": reallocations, "concurrent_claims": concurrent,
        "released": released,
        "messages": msg, "message_bin_s": MESSAGE_BIN_S,
        "drop_reasons": dict(drop_reasons), "outages": outages,
        "delivery_by_window": delivery,
        "llm": llm, "guardian": guardian, "progress": progress,
        "first_target_times": targets,
    }


# --- coordination defects the timeline makes visible --------------------------


def findings(tl) -> List[str]:
    """Things a reader should look at, phrased as observations, not verdicts.

    These are the defects aggregate numbers hid during the pilot - kept as
    automatic checks so a regression shows up in the summary, not only in a
    picture somebody has to remember to open."""
    out = []
    n_sectors = len((tl.get("tracks") or {}).get("sectors", {})) or None
    dups = [p for p in tl["progress"] if p["duplicate"]]
    if dups:
        out.append(f"{len(dups)} repeated sweep(s) of an already-searched sector: "
                   + ", ".join(f"{p['sector']} by {p['vehicle']} at {p['t']:.0f}s"
                               for p in dups))
    distinct = tl["progress"][-1]["distinct"] if tl["progress"] else 0
    if n_sectors and distinct < n_sectors:
        out.append(f"only {distinct}/{n_sectors} sectors searched")
    for v, t in tl["faults"].items():
        after = [p for p in tl["progress"] if p["vehicle"] == v and p["t"] > t + 1e-6]
        if after:
            out.append(f"{v} finished a sweep after it was stopped at {t:.0f}s")
    total = sum(tl["messages"]["sent"]) or 0
    dropped = sum(tl["messages"]["dropped"])
    if total and dropped / total > 0.7:
        top = max(tl["drop_reasons"], key=tl["drop_reasons"].get)
        out.append(f"{100 * dropped / total:.0f}% of messages lost "
                   f"(mostly {top}) - coordination is close to impossible")
    asked = [x for x in tl["llm"] if not x.get("by_design")]
    fb = [x for x in asked if x["fallback"]]
    if asked and len(fb) / len(asked) > 0.2:
        causes = sorted({x["cause"] or "?" for x in fb})
        out.append(f"LLM fell back on {len(fb)}/{len(asked)} decisions it was "
                   f"asked to make ({', '.join(causes)})")
    return out


# --- drawing ----------------------------------------------------------------


def plot(tl, path, dpi=110):
    """Draw the nine views into one PNG. Needs matplotlib; nothing else does."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon

    vehicles = tl["vehicles"]
    colours = plt.get_cmap("tab10")
    vcol = {v: colours(i % 10) for i, v in enumerate(vehicles)}
    end = max(tl["end"], 1.0)

    fig = plt.figure(figsize=(16, 13))
    gs = fig.add_gridspec(6, 2, height_ratios=[1.1, 1.1, 0.8, 0.8, 0.8, 0.9],
                          hspace=0.55, wspace=0.18)
    m = tl["manifest"]
    title = (f"{tl['run']}   arch {m.get('architecture_key', '?')}   "
             f"{len(vehicles)} drones   {m.get('network_profile', '?')}   "
             f"fault {m.get('failure_profile', '?')}   seed {m.get('random_seed', '?')}")
    r = tl["result"]
    if r:
        title += (f"\ncoverage {r.get('coverage')}   dup {r.get('duplicated_sectors')}"
                  f"   home {r.get('drones_home')}   t {r.get('mission_time_s')} s"
                  f"   delivery {r.get('delivery_rate')}")
    fig.suptitle(title, fontsize=11)

    # 1. trajectories
    ax = fig.add_subplot(gs[0:2, 0])
    tr = tl["tracks"] or {}
    for sid, corners in (tr.get("sectors") or {}).items():
        if corners:
            ax.add_patch(Polygon(corners, closed=True, fill=False, ls="--",
                                 ec="grey", lw=0.8))
            cx = sum(c[0] for c in corners) / len(corners)
            cy = sum(c[1] for c in corners) / len(corners)
            ax.text(cx, cy, sid, color="grey", ha="center", va="center", fontsize=9)
    for zid, poly in (tr.get("restricted_zones") or {}).items():
        ax.add_patch(Polygon(poly, closed=True, fc="red", alpha=0.25, ec="red"))
    if tr.get("base"):
        ax.plot(*tr["base"][:2], "ks", ms=8, label="base")
    for tid, p in (tr.get("targets") or {}).items():
        ax.plot(p[0], p[1], "r*", ms=11)
        ax.annotate(tid, p[:2], fontsize=8, xytext=(3, 3), textcoords="offset points")
    for v, pts in (tr.get("tracks") or {}).items():
        if pts:
            ax.plot([p[0] for p in pts], [p[1] for p in pts], "-", lw=1.2,
                    color=vcol.get(v, "k"), label=v)
            ax.plot(pts[-1][0], pts[-1][1], "o", color=vcol.get(v, "k"))
            if v in tl["faults"]:
                ax.plot(pts[-1][0], pts[-1][1], "kx", ms=12, mew=2)
    ax.set_aspect("equal", adjustable="datalim")
    ax.set_title("Trajectories (x = stopped drone)", fontsize=10)
    ax.legend(fontsize=7, loc="upper right")
    ax.grid(alpha=0.2)

    # 2. mission progress
    ax = fig.add_subplot(gs[0, 1])
    pr = tl["progress"]
    if pr:
        xs = [0] + [p["t"] for p in pr]
        ys = [0] + [p["distinct"] for p in pr]
        ax.step(xs, ys, where="post", color="tab:green", label="distinct sectors")
        ax.step(xs, [0] + list(range(1, len(pr) + 1)), where="post", ls=":",
                color="grey", label="sweeps incl. duplicates")
        for p in pr:
            if p["duplicate"]:
                ax.plot(p["t"], p["distinct"], "rv", ms=7)
    for tid, t in tl["first_target_times"].items():
        ax.axvline(t, color="red", lw=0.6, ls="--")
    ax.set_xlim(0, end)
    ax.set_title("Mission progress (red v = duplicate sweep, red line = target first seen)",
                 fontsize=10)
    ax.legend(fontsize=7)

    # 3. messages
    ax = fig.add_subplot(gs[1, 1])
    bw = tl["message_bin_s"]
    xs = [i * bw for i in range(len(tl["messages"]["sent"]))]
    ax.bar(xs, tl["messages"]["received"], width=bw, align="edge",
           color="tab:blue", label="received")
    ax.bar(xs, tl["messages"]["dropped"], width=bw, align="edge",
           bottom=tl["messages"]["received"], color="tab:red", alpha=0.7,
           label="dropped")
    reasons = ", ".join(f"{k} {v}" for k, v in sorted(tl["drop_reasons"].items(),
                                                       key=lambda kv: -kv[1]))
    ax.set_xlim(0, end)
    ax.set_title(f"Messages per {bw:.0f} s (drops: {reasons or 'none'})", fontsize=10)
    ax.legend(fontsize=7)

    def lanes(ax, title):
        ax.set_yticks(range(len(vehicles)))
        ax.set_yticklabels(vehicles, fontsize=8)
        ax.set_ylim(-0.6, len(vehicles) - 0.4)
        ax.set_xlim(0, end)
        ax.invert_yaxis()
        ax.set_title(title, fontsize=10)
        for v, t in tl["faults"].items():
            if v in vehicles:
                y = vehicles.index(v)
                ax.plot([t], [y], "kx", ms=10, mew=2)
                ax.hlines(y, t, end, colors="k", linestyles=":", lw=1)

    # 4. active task
    ax = fig.add_subplot(gs[2, :])
    task_names = sorted({x for v in vehicles for _, _, x in tl["tasks"][v]})
    tcol = {t: colours(i % 10) for i, t in enumerate(task_names)}
    for y, v in enumerate(vehicles):
        for a, b, task in tl["tasks"][v]:
            ax.barh(y, max(b - a, 0.5), left=a, color=tcol[task], height=0.6)
            ax.text(a + 1, y, task.replace("SEARCH_SECTOR_", ""), va="center",
                    fontsize=7, color="white")
    for rr in tl["reallocations"]:
        y = vehicles.index(rr["to"]) if rr["to"] in vehicles else 0
        ax.annotate("", xy=(rr["t"], y), xytext=(rr["t"], y - 0.45),
                    arrowprops=dict(arrowstyle="->", color="k"))
    for cc in tl.get("concurrent_claims", []):
        if cc["vehicle"] in vehicles:
            ax.plot(cc["t"], vehicles.index(cc["vehicle"]) - 0.38, "rv", ms=6)
    lanes(ax, "Active task by drone (black arrow = taken over from another drone, "
              "red v = same task already being worked by another drone)")

    # 5. role
    ax = fig.add_subplot(gs[3, :])
    role_names = sorted({x for v in vehicles for _, _, x in tl["roles"][v]})
    rcol = {r_: plt.get_cmap("Set2")(i % 8) for i, r_ in enumerate(role_names)}
    for y, v in enumerate(vehicles):
        for a, b, role in tl["roles"][v]:
            ax.barh(y, max(b - a, 0.5), left=a, color=rcol[role], height=0.6)
            ax.text(a + 1, y, role, va="center", fontsize=7)
    lanes(ax, "Role by drone")

    # 6. comms outages
    ax = fig.add_subplot(gs[4, :])
    for y, v in enumerate(vehicles):
        for t0, n, frac in tl.get("delivery_by_window", {}).get(v, []):
            ax.barh(y, OUTAGE_BIN_S, left=t0, height=0.6,
                    color=plt.get_cmap("RdYlGn")(frac), ec="none")
        for a, b in tl["outages"][v]:
            ax.barh(y, b - a, left=a, height=0.6, fill=False, ec="k", lw=1.2)
    lanes(ax, f"Messages reaching each drone per {OUTAGE_BIN_S:.0f} s (green = all "
              f"delivered, red = none; black box = outage, nothing got through)")

    # 7. LLM decisions + guardian interventions
    ax = fig.add_subplot(gs[5, :])
    for x in tl["llm"]:
        if x["vehicle"] in vehicles:
            y = vehicles.index(x["vehicle"])
            if x.get("by_design"):
                ax.plot(x["t"], y, ".", ms=4, color="grey")
            else:
                ax.plot(x["t"], y, "o", ms=6,
                        mfc="none" if x["fallback"] else "tab:purple", mec="tab:purple")
    for g in tl["guardian"]:
        if g["vehicle"] in vehicles:
            ax.plot(g["t"], vehicles.index(g["vehicle"]), "x", color="red", ms=9, mew=2)
    lanes(ax, "LLM decisions (filled = model, hollow = fallback, grey = deterministic "
              "by design) and guardian interventions (red x)")
    ax.set_xlabel("simulated time (s)")

    found = findings(tl)
    if found:
        fig.text(0.01, 0.005, "Findings: " + "  |  ".join(found), fontsize=8,
                 color="darkred", wrap=True)

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    fig.savefig(path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return path
