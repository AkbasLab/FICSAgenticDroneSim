"""Phase 17: one run's timeline, as AUV-16 asks for each pilot run (17.2).

    model = timeline("runs/experiments/<batch>/<run_id>")      # what happened, lane by lane (testable)
    html = render(model)                                        # one self-contained page, inline SVG

AUV-16: "Aggregate statistics alone will hide coordination defects. A team that
thrashes roles twenty times and a team that adapts twice can produce the same
mission score. Only the timeline shows the difference." For each drone, over
the flight: its TASK (from each assignment to its release or its next task),
its ROLE, its SKILLS (coloured by how each ended), its communication OUTAGES
(any 3 s or more in which it received nothing -- the health ladder's first
rung), its MODEL decisions and GUARDIAN interventions, and its marks (stopped,
target found). For the team: messages over time (sent, received, dropped, in
5 s bins), partitions, task REALLOCATIONS (an assignment beyond a task's
first), and MISSION PROGRESS -- the searched fraction over time, by the judge's
own rule, so its end is the judge's coverage.

Read from the run's directory alone (Phase 14/15): manifest, report, event log, trajectories.
"""

from __future__ import annotations

import gzip
import html as _html
import io
import json
import os
from typing import Any

OUTAGE_S = 3.0            # the health ladder's first rung: three heartbeats missed
BIN_S = 5.0
SKILL_COLOURS = {"success": "#3b8f5a", "aborted": "#b9a24a", "failure": "#c0504d", "failed": "#c0504d",
                 "timeout": "#c0504d", "unknown": "#888888"}
ROLE_COLOURS = {"scout": "#4e79a7", "relay": "#e15759", "reserve": "#9c9c9c"}


def _load(run_dir: str) -> tuple[dict, dict, list[dict], dict | None]:
    with io.open(os.path.join(run_dir, "manifest.json"), encoding="utf-8") as h:
        manifest = json.load(h)
    with io.open(os.path.join(run_dir, "report.json"), encoding="utf-8") as h:
        report = json.load(h)
    with gzip.open(os.path.join(run_dir, "events.jsonl.gz"), "rt", encoding="utf-8") as h:
        events = [json.loads(line) for line in h]
    traj = None
    path = os.path.join(run_dir, "trajectories.json.gz")
    if os.path.isfile(path):
        with gzip.open(path, "rt", encoding="utf-8") as h:
            traj = json.load(h)
    return manifest, report, events, traj


def _spans(changes: list[tuple[float, str | None]], end: float) -> list[tuple[float, float, str]]:
    """(time, label or None) changes -> (start, end, label) spans, None closing a span."""
    out, cur = [], None
    for t, label in sorted(changes, key=lambda c: c[0]):
        if cur is not None and t > cur[0]:
            out.append((cur[0], t, cur[1]))
        cur = (t, label) if label is not None else None
    if cur is not None and end > cur[0]:
        out.append((cur[0], end, cur[1]))
    return out


def silences(heard: list[float], until: float, start: float = 0.0) -> list[tuple[float, float]]:
    """The spans of OUTAGE_S or more, between `start` and `until`, in which nothing was received."""
    out, prev = [], start
    for t in sorted(heard) + [until]:
        if t > until:
            break
        if t - prev >= OUTAGE_S - 1e-9:
            out.append((prev, t))
        prev = max(prev, t)
    return out


def progress(scenario: Any, traj: dict, window: float, step: float = 1.0) -> list[tuple[float, float]]:
    """The searched fraction over time, by the judge's rule (`simulator/coverage.covered_at`)."""
    import numpy as np

    from ..simulator.coverage import covered_at, searchable_cells
    from ..simulator.trajectory import Knot, Trajectory
    trajs = [Trajectory(d, [Knot(float(k[0]), float(k[1]), float(k[2]), float(k[3]), bool(k[4])) for k in ks])
             for d, ks in traj.items() if ks]
    start = min(t.knots[0].t for t in trajs)
    cells, _ = searchable_cells(scenario, 1.0)
    first = covered_at(cells, trajs, scenario.detection.radius_m, scenario.detection.min_observation_s, start,
                       start + window)
    times = np.sort(first[np.isfinite(first)]) - start
    n = len(cells)
    out, t = [], 0.0
    while t <= window + 1e-9:
        out.append((round(t, 3), float(np.searchsorted(times, t, side="right")) / n))
        t += step
    if out[-1][0] < window:
        out.append((round(window, 3), float(len(times)) / n))
    return out


def timeline(run_dir: str) -> dict[str, Any]:
    from .scenarios import load_scenario
    manifest, report, events, traj = _load(run_dir)
    cfg = manifest["config"]
    rep = report["report"]
    window = rep["window_s"]
    by = lambda kind: [e for e in events if e["type"] == kind]  # noqa: E731
    roster = by("MISSION_STARTED")[0]["roster"]
    lanes: dict[str, dict[str, list]] = {}
    for d in roster:
        tasks = [(e["t"], e["task"]) for e in by("TASK_ASSIGNED") if e["drone"] == d]
        tasks += [(e["t"], None) for e in by("TASK_RELEASED") if e["drone"] == d]
        roles = [(e["t"], e["role"]) for e in by("ROLE_CHANGED") if e["drone"] == d]
        started = {e["serial"]: e for e in by("SKILL_STARTED") if e["drone"] == d}
        skills = [(started[e["serial"]]["t"], e["t"], e["skill"], e["status"]) for e in by("SKILL_COMPLETED")
                  if e["drone"] == d and e["serial"] in started]
        stop = next((e["t"] for e in by("FAULT_INJECTED") if e["fault"] == "stop" and e["drone"] == d), None)
        heard = [e["t"] for e in by("MESSAGE_RECEIVED") if e["drone"] == d]
        last = stop if stop is not None else max([s[1] for s in skills] + [0.0])
        outages = silences(heard, last) if len(roster) > 1 else []
        marks = [(e["t"], f"found {e['target']}") for e in by("TARGET_FOUND") if e["drone"] == d]
        if stop is not None:
            marks.append((stop, "stopped"))
        lanes[d] = {
            "task": _spans(tasks, stop if stop is not None else window),
            "role": _spans(roles, stop if stop is not None else window),
            "skill": skills, "outage": outages,
            "llm": [(e["t"], e["kind"], e.get("tool")) for e in by("LLM_CALLED") if e["drone"] == d],
            "guardian": [(e["t"], e["outcome"]) for e in by("GUARDIAN_INTERVENED") if e["drone"] == d],
            "marks": sorted(marks)}
    bins: dict[int, list[int]] = {}
    for e in events:
        k = {"MESSAGE_SENT": 0, "MESSAGE_RECEIVED": 1, "MESSAGE_DROPPED": 2}.get(e["type"])
        if k is not None:
            bins.setdefault(int(e["t"] // BIN_S), [0, 0, 0])[k] += 1
    seen: dict[str, int] = {}
    reallocations = []
    for e in by("TASK_ASSIGNED"):
        seen[e["task"]] = seen.get(e["task"], 0) + 1
        if seen[e["task"]] > 1:
            reallocations.append((e["t"], e["task"], e["drone"]))
    team = {"messages": [(k * BIN_S, *v) for k, v in sorted(bins.items())],
            "partitions": [(e["t"], e["until_s"], e["groups"]) for e in by("FAULT_INJECTED") if e["fault"] == "partition"],
            "reallocations": reallocations,
            "progress": progress(load_scenario(cfg["scenario"]), traj, window) if traj else []}
    end = by("MISSION_COMPLETED")[0]
    return {"run_id": manifest["run_id"], "config": cfg, "window_s": window, "roster": roster, "lanes": lanes,
            "team": team, "outcome": {"success": rep["success"], "met": end["met"], "completion_s": rep["completion_s"],
                                      "coverage": rep["coverage"]["fraction"]}}


# ------------------------------------------------------------------ the page

def render(m: dict[str, Any], width: int = 1200) -> str:
    left, right, row, gap = 150, 20, 14, 4
    plot = width - left - right
    T = max(m["window_s"], 1.0)
    x = lambda t: left + plot * max(0.0, min(t, T)) / T  # noqa: E731
    parts, y = [], 30
    esc = _html.escape

    def label(text: str, yy: float, bold: bool = False) -> None:
        parts.append(f'<text x="{left - 8}" y="{yy + row - 3}" text-anchor="end" class="{"b" if bold else "l"}">'
                     f'{esc(text)}</text>')

    def bar(t0: float, t1: float, yy: float, colour: str, title: str) -> None:
        w = max(1.0, x(t1) - x(t0))
        parts.append(f'<rect x="{x(t0):.1f}" y="{yy}" width="{w:.1f}" height="{row}" fill="{colour}">'
                     f'<title>{esc(title)}</title></rect>')

    def tick(t: float, yy: float, colour: str, title: str, h: float = row) -> None:
        parts.append(f'<line x1="{x(t):.1f}" x2="{x(t):.1f}" y1="{yy}" y2="{yy + h}" stroke="{colour}" '
                     f'stroke-width="2"><title>{esc(title)}</title></line>')

    for g0, g1, groups in m["team"]["partitions"]:
        parts.append(f'<rect x="{x(g0):.1f}" y="0" width="{x(g1) - x(g0):.1f}" height="100%" class="part">'
                     f'<title>partition {esc(str(groups))}</title></rect>')
    for d in m["roster"]:
        lane = m["lanes"][d]
        label(d, y, bold=True)
        y += row + gap
        label("task", y)
        for t0, t1, name in lane["task"]:
            bar(t0, t1, y, "#7aa6c2", f"{d} {name} {t0:.1f}-{t1:.1f} s")
            parts.append(f'<text x="{x(t0) + 3:.1f}" y="{y + row - 3}" class="in">{esc(name)}</text>')
        y += row + gap
        label("role", y)
        for t0, t1, name in lane["role"]:
            bar(t0, t1, y, ROLE_COLOURS.get(name, "#999"), f"{d} {name} {t0:.1f}-{t1:.1f} s")
        y += row + gap
        label("skills", y)
        for t0, t1, name, status in lane["skill"]:
            bar(t0, t1, y, SKILL_COLOURS.get(status, "#888"), f"{d} {name} {status} {t0:.1f}-{t1:.1f} s")
        y += row + gap
        label("heard nothing", y)
        for t0, t1 in lane["outage"]:
            bar(t0, t1, y, "#d98c3a", f"{d} received nothing {t0:.1f}-{t1:.1f} s")
        y += row + gap
        label("model · guardian · marks", y)
        for t, kind, tool in lane["llm"]:
            tick(t, y, "#6a51a3" if kind == "llm" else "#c0504d", f"{d} model {kind} {tool} at {t:.1f} s", row / 2)
        for t, outcome in lane["guardian"]:
            tick(t, y + row / 2, "#c0504d", f"{d} guardian {outcome} at {t:.1f} s", row / 2)
        for t, what in lane["marks"]:
            tick(t, y, "#222", f"{d} {what} at {t:.1f} s")
            parts.append(f'<text x="{x(t) + 3:.1f}" y="{y + row - 3}" class="in">{esc(what)}</text>')
        y += row + 2 * gap + 6
    label("reallocations", y, bold=True)
    for t, task, d in m["team"]["reallocations"]:
        tick(t, y, "#e15759", f"{task} to {d} at {t:.1f} s")
    y += row + 2 * gap
    msgs = m["team"]["messages"]
    peak = max([s + r + dr for _, s, r, dr in msgs] + [1])
    h = 60
    label(f"messages / {BIN_S:g} s (max {peak})", y + h - row, bold=True)
    for t0, sent, recv, drop in msgs:
        w = max(1.0, x(t0 + BIN_S) - x(t0) - 1)
        yy = y + h
        for n, colour, what in ((recv, "#3b8f5a", "received"), (sent, "#4e79a7", "sent"), (drop, "#c0504d", "dropped")):
            hh = h * n / peak
            yy -= hh
            parts.append(f'<rect x="{x(t0):.1f}" y="{yy:.1f}" width="{w:.1f}" height="{hh:.1f}" fill="{colour}">'
                         f'<title>{t0:g}-{t0 + BIN_S:g} s: {n} {what}</title></rect>')
    y += h + 2 * gap
    prog = m["team"]["progress"]
    if prog:
        label("searched", y + h - row, bold=True)
        pts = " ".join(f"{x(t):.1f},{y + h - h * f:.1f}" for t, f in prog)
        parts.append(f'<polyline points="{pts}" fill="none" stroke="#3b8f5a" stroke-width="2"/>')
        parts.append(f'<text x="{x(prog[-1][0]) - 4:.1f}" y="{y + h - h * prog[-1][1] - 4:.1f}" text-anchor="end" '
                     f'class="in">{100 * prog[-1][1]:.1f} %</text>')
        y += h + 2 * gap
    for t in range(0, int(T) + 1, 30):
        parts.append(f'<line x1="{x(t):.1f}" x2="{x(t):.1f}" y1="20" y2="{y}" class="grid"/>'
                     f'<text x="{x(t):.1f}" y="14" text-anchor="middle" class="l">{t} s</text>')
    o, c = m["outcome"], m["config"]
    head = (f"{c['architecture']} · {c['scenario']} · {c['network']} · {c['failure']} · seed {c['seed']} · "
            f"{c['planner']} — {'met' if o['met'] else 'NOT met'}, "
            + (f"{o['completion_s']:.1f} s" if o["completion_s"] is not None else "not completed")
            + f", coverage {100 * o['coverage']:.1f} %")
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{y + 10}" viewBox="0 0 {width} {y + 10}">'
           + "".join(parts) + "</svg>")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Timeline {esc(m['run_id'])}</title>
<style>
:root {{ color-scheme: light dark; --fg: #1d1d1f; --bg: #ffffff; --grid: #e4e4e4; --part: rgba(225,87,89,.10); }}
@media (prefers-color-scheme: dark) {{ :root {{ --fg: #e8e8e8; --bg: #161616; --grid: #2f2f2f; --part: rgba(225,87,89,.18); }} }}
body {{ background: var(--bg); color: var(--fg); font: 14px system-ui, sans-serif; margin: 16px; }}
svg text {{ fill: var(--fg); font: 11px system-ui, sans-serif; }} svg text.b {{ font-weight: 600; }}
svg text.in {{ font-size: 10px; }} .grid {{ stroke: var(--grid); }} .part {{ fill: var(--part); }}
.wrap {{ overflow-x: auto; }}
</style></head><body>
<h1 style="font-size:18px">{esc(m['run_id'])}</h1>
<p>{esc(head)}</p>
<p style="font-size:12px">Task, role and skills per drone (skills green = success, ochre = aborted, red = failed); orange =
received nothing for {OUTAGE_S:g} s or more; violet ticks = model decisions (red = fallback); lower red ticks = guardian
interventions; shaded = a partition. Hover anything for its details.</p>
<div class="wrap">{svg}</div>
</body></html>
"""


def write_timeline(run_dir: str, out: str | None = None) -> str:
    path = out or os.path.join(run_dir, "timeline.html")
    with io.open(path, "w", encoding="utf-8", newline="\n") as h:
        h.write(render(timeline(run_dir)))
    return path
