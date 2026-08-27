"""Render the canonical mission layout as a figure for the README.

Draws the scenario straight from its YAML - sectors, targets, no-fly zone, base
and drone starts - and optionally overlays the flown paths from a scripted run,
so the picture can never drift out of sync with the actual config.

    python scripts/plot_mission_layout.py
    python scripts/plot_mission_layout.py --paths     # overlay the flown sweep
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon, Rectangle

from agentic_uav.simulator.scenario_manager import load_scenario

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SCENARIO = os.path.join(ROOT, "configs", "missions", "search_relay_001.yaml")
DEFAULT_OUT = os.path.join(ROOT, "docs", "images", "mission_layout.png")

SECTOR_COLORS = ["#4C72B0", "#DD8452", "#55A868", "#C44E52"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default=DEFAULT_SCENARIO)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--paths", action="store_true",
                    help="overlay the scripted controller's flown paths")
    args = ap.parse_args()

    scenario = load_scenario(args.scenario)
    fig, ax = plt.subplots(figsize=(8, 8))

    # search sectors
    for i, s in enumerate(scenario.sectors):
        r = s.footprint
        color = SECTOR_COLORS[i % len(SECTOR_COLORS)]
        ax.add_patch(Rectangle((r.min_x, r.min_y), r.max_x - r.min_x,
                               r.max_y - r.min_y, facecolor=color, alpha=0.15,
                               edgecolor=color, linewidth=1.8))
        ax.text((r.min_x + r.max_x) / 2, r.max_y - 4, s.sector_id,
                ha="center", va="top", fontsize=13, color=color, weight="bold")

    # restricted zones
    for z in scenario.restricted_zones:
        ax.add_patch(Polygon(z.polygon, closed=True, facecolor="#B0B0B0",
                             alpha=0.55, edgecolor="black", hatch="///",
                             linewidth=1.5))
        cx = sum(p[0] for p in z.polygon) / len(z.polygon)
        cy = sum(p[1] for p in z.polygon) / len(z.polygon)
        ax.text(cx, cy, f"{z.zone_id}\nno-fly", ha="center", va="center",
                fontsize=9, weight="bold")

    # optional flown paths
    if args.paths:
        from agentic_uav.experiments.mission_runner import (
            assign_sectors, SEARCH_SPEED)
        from agentic_uav.control.skill_executor import _lawnmower
        from agentic_uav.control import skills as sk
        assignment = assign_sectors(scenario)
        for i, v in enumerate(scenario.vehicles):
            wps = []
            for sector in assignment.get(v.vehicle_id, []):
                r = sector.footprint
                wps.extend(_lawnmower(sk.SearchRegionCommand(
                    min_x=r.min_x, min_y=r.min_y, max_x=r.max_x, max_y=r.max_y,
                    altitude=sector.altitude, lane_spacing_m=8.0,
                    speed_mps=SEARCH_SPEED)))
            if wps:
                ax.plot([p.x for p in wps], [p.y for p in wps],
                        color=SECTOR_COLORS[i % len(SECTOR_COLORS)],
                        linewidth=0.9, alpha=0.75, zorder=2)

    # targets
    for t in scenario.targets:
        ax.add_patch(plt.Circle((t.position.x, t.position.y),
                                t.detection_radius_m, color="crimson",
                                alpha=0.18, zorder=3))
        ax.plot(t.position.x, t.position.y, marker="*", markersize=20,
                color="crimson", zorder=4)
        ax.text(t.position.x + 4, t.position.y + 4, t.target_id,
                fontsize=11, color="crimson", weight="bold", zorder=4)

    # base + drone starts
    b = scenario.base.position
    ax.plot(b.x, b.y, marker="s", markersize=13, color="black", zorder=5)
    ax.text(b.x + 3, b.y - 7, "base", fontsize=11, weight="bold", zorder=5)
    ax.add_patch(plt.Circle((b.x, b.y), scenario.base.comm_range_m,
                            fill=False, linestyle=":", color="black",
                            alpha=0.5, zorder=1))
    ax.plot([v.start.x for v in scenario.vehicles],
            [v.start.y for v in scenario.vehicles],
            marker="^", markersize=9, linestyle="none", color="#333333",
            zorder=5, label=f"{len(scenario.vehicles)} drones")

    lim = 70
    ax.set_xlim(-lim, lim)
    ax.set_ylim(-lim, lim)
    ax.set_aspect("equal")
    ax.set_xlabel("x (m)")
    ax.set_ylabel("y (m)")
    ax.set_title(f"Canonical mission: {scenario.scenario_id}\n"
                 f"{len(scenario.sectors)} sectors · {len(scenario.targets)} targets · "
                 f"deadline {scenario.mission.deadline_s:.0f}s", fontsize=12)
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(alpha=0.2, linestyle="--")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    fig.tight_layout()
    fig.savefig(args.out, dpi=150)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
