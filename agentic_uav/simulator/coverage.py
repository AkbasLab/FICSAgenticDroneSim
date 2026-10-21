"""How much of the search area a flight searched (AUV-05, 4.3: "a specified coverage threshold").

    cov = coverage(scenario, trajectories, start, end)
    cov.fraction                  # of the searchable area
    cov.time_to(0.95)             # when the team first reached 95 %, or None

SEARCHED MEANS A TARGET THERE WOULD HAVE BEEN DETECTED. A point counts as
searched once some airborne drone has held it within the detection radius,
horizontally, for the minimum observation time without a break -- exactly
the rule `mission_world.detections` applies to a target. So coverage is the
chance that a target placed uniformly at random would have been found, and
coverage and detection cannot disagree: a target at a searched point is
detected. A drone that merely passed within the radius has not searched
there, and neither have two drones that each saw a point for half the time.

THE SEARCHABLE AREA is the sectors, less any restricted zone: where a target
can be (`place_targets`). It is measured on a grid of `cell_m` cells, each
judged at its centre; the dwell at each centre is solved exactly, leg by leg,
as in `mission_world`, for every cell at once. The grid is the only
approximation, and its size is reported with the result.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..core.scenario import Scenario
from .trajectory import Trajectory, breakpoints, intervals

DEFAULT_CELL_M = 1.0
_EPS = 1e-9


@dataclass(frozen=True)
class Coverage:
    cell_m: float
    cells: int                               # searchable cells
    fraction: float
    by_sector: dict[str, float]
    covered_times: tuple[float, ...]         # each covered cell's moment, sorted

    def time_to(self, fraction: float) -> float | None:
        """When coverage first reached `fraction`, or None if it never did."""
        if fraction <= 0:
            return None if not self.cells else (self.covered_times[0] if self.covered_times else None)
        needed = math.ceil(fraction * self.cells - _EPS)
        if needed > len(self.covered_times):
            return None
        return self.covered_times[needed - 1]


def searchable_cells(scenario: Scenario, cell_m: float = DEFAULT_CELL_M) -> tuple[np.ndarray, np.ndarray]:
    """Cell centres (N x 2) over the sectors outside every zone, and each one's sector index."""
    if cell_m <= 0:
        raise ValueError("cell size must be positive")
    points, owner = [], []
    for i, sector in enumerate(scenario.sectors):
        r = sector.region
        xs = np.arange(r.x_min + cell_m / 2.0, r.x_max, cell_m)
        ys = np.arange(r.y_min + cell_m / 2.0, r.y_max, cell_m)
        gx, gy = np.meshgrid(xs, ys, indexing="ij")
        pts = np.column_stack((gx.ravel(), gy.ravel()))
        keep = np.ones(len(pts), dtype=bool)
        for zone in scenario.restricted_zones:
            b = zone.polygon.bounds()
            near = np.flatnonzero((pts[:, 0] >= b.x_min) & (pts[:, 0] <= b.x_max)
                                  & (pts[:, 1] >= b.y_min) & (pts[:, 1] <= b.y_max))
            for j in near:
                if zone.polygon.contains(pts[j, 0], pts[j, 1]):
                    keep[j] = False
        points.append(pts[keep])
        owner.append(np.full(int(keep.sum()), i))
    return np.concatenate(points), np.concatenate(owner)


def covered_at(cells: np.ndarray, trajectories: list[Trajectory], radius_m: float,
               min_observation_s: float, start: float, end: float) -> np.ndarray:
    """For each cell, the first moment any drone completed a dwell over it (inf if none)."""
    first = np.full(len(cells), np.inf)
    r2 = radius_m * radius_m
    for traj in trajectories:
        run_start = np.full(len(cells), np.nan)
        run_end = np.full(len(cells), -np.inf)
        for u, v in intervals(breakpoints((traj,), start, end)):
            leg = traj.leg_over(u, v)
            if not leg.airborne:
                run_end[:] = -np.inf                     # on the ground: every dwell breaks
                continue
            span = v - u
            d0 = np.array(leg.p0[:2]) - cells            # drone minus cell, at u
            w = (np.array(leg.p1[:2]) - np.array(leg.p0[:2])) / span
            a = float(w @ w)
            b = 2.0 * (d0 @ w)
            c = np.einsum("ij,ij->i", d0, d0) - r2
            if a == 0.0:
                inside = c <= 0.0
                lo = np.zeros(len(cells))
                hi = np.full(len(cells), span)
            else:
                disc = b * b - 4.0 * a * c
                root = np.sqrt(np.maximum(disc, 0.0))
                lo = np.maximum(0.0, (-b - root) / (2.0 * a))
                hi = np.minimum(span, (-b + root) / (2.0 * a))
                inside = (disc >= 0.0) & (lo <= hi)
            lo, hi = u + lo, u + hi
            carried = inside & (lo <= run_end + _EPS)    # the dwell goes on across the knot
            run_start = np.where(inside & ~carried, lo, run_start)
            run_end = np.where(inside, hi, -np.inf)
            reach = run_start + min_observation_s
            done = inside & (reach <= run_end + _EPS)
            first = np.where(done, np.minimum(first, reach), first)
    return first


def coverage(scenario: Scenario, trajectories: dict[str, Trajectory] | list[Trajectory],
             start: float, end: float, cell_m: float = DEFAULT_CELL_M) -> Coverage:
    trajs = list(trajectories.values()) if isinstance(trajectories, dict) else list(trajectories)
    cells, owner = searchable_cells(scenario, cell_m)
    times = covered_at(cells, trajs, scenario.detection.radius_m,
                       scenario.detection.min_observation_s, start, end)
    hit = np.isfinite(times)
    by_sector = {}
    for i, sector in enumerate(scenario.sectors):
        mine = owner == i
        by_sector[sector.id] = float(hit[mine].mean()) if mine.any() else 0.0
    return Coverage(cell_m, len(cells), float(hit.mean()) if len(cells) else 0.0, by_sector,
                    tuple(float(t) for t in np.sort(times[hit])))
