"""NavRL's pretrained policy (Xu et al., arXiv 2409.15634) as a leg planner for fly_leg_with_planner.

NavRL is not part of this repo: point NAVRL_DIR (or the constructor) at a checkout of github.com/Zhefan-Xu/NavRL's
`quick-demos` folder and run in an environment that has its dependencies (torch). It is loaded on first use, so nothing
else here needs torch.

What the policy sees is the lab's own situation, not a real lidar: the zones that are active now, as rectangles, turned
into the same ray distances NavRL reads from its lidar (rect_ray below). It does not know about targets or batteries;
it only chooses a velocity toward the goal that stays clear of the rectangles it can "see" (4 m range).
"""

import os
import sys
import threading

import numpy as np

MAX_RAY_M = 4.0
DEFAULT_NAVRL_DIR = os.path.expanduser("~/NavRL/quick-demos")


def rect_ray(robot_pos, angle, rects, max_range=MAX_RAY_M, safety_margin=0.0):
    """Distance along `angle` from `robot_pos` to the nearest rectangle edge, or max_range. 0 if already inside one."""
    dx, dy = np.cos(angle), np.sin(angle)
    best = max_range
    px, py = robot_pos[0], robot_pos[1]
    for x0, x1, y0, y1 in rects:
        if x0 <= px <= x1 and y0 <= py <= y1:
            return 0.0
        t0, t1, ok = 0.0, max_range, True
        for p, d, lo, hi in ((px, dx, x0, x1), (py, dy, y0, y1)):
            if abs(d) < 1e-9:
                if p < lo or p > hi:
                    ok = False
                    break
            else:
                ta, tb = (lo - p) / d, (hi - p) / d
                if ta > tb:
                    ta, tb = tb, ta
                t0, t1 = max(t0, ta), min(t1, tb)
                if t0 > t1:
                    ok = False
                    break
        if ok:
            best = min(best, t0)
    return best


class NavRLPlanner:
    def __init__(self, navrl_dir=None):
        self.navrl_dir = navrl_dir or os.environ.get("NAVRL_DIR") or DEFAULT_NAVRL_DIR
        self._lock = threading.Lock()   # one policy object shared by every drone's thread
        self._loaded = False

    def _load(self):
        import torch
        here = os.getcwd()
        sys.path.insert(0, self.navrl_dir)
        try:
            os.chdir(self.navrl_dir)    # the policy loads its checkpoint from a path relative to this folder
            import utils as navutils
            from agent import Agent
            from utils import get_robot_state
            navutils.ray_cast_distance = rect_ray
            self._torch, self._navutils, self._get_robot_state = torch, navutils, get_robot_state
            self._device = torch.device("cpu")
            self._agent = Agent(device=self._device)
        finally:
            os.chdir(here)
        self._loaded = True

    def begin_leg(self, start_xy, goal_xy):
        """Starts one leg and returns a handle for it. The leg direction and last velocity live in the handle, not
        here, because one planner object is shared by every drone thread."""
        with self._lock:
            if not self._loaded:
                self._load()
        return _Leg(self, np.array(goal_xy, float) - np.array(start_xy, float))

    def _plan(self, target_dir, vel, pos, goal, zone_rects):
        with self._lock:
            torch = self._torch
            state = self._get_robot_state(pos, goal, vel, target_dir, device=self._device)
            lidar, _, _ = self._navutils.get_ray_cast(
                pos, zone_rects, max_range=MAX_RAY_M, hres_deg=10.0, vfov_angles_deg=[-10.0, 0.0, 10.0, 20.0],
                start_angle_deg=float(np.degrees(np.arctan2(target_dir[1], target_dir[0]))), device=self._device)
            dyn = torch.zeros((1, 1, 5, 10), dtype=torch.float, device=self._device)
            tdir = torch.tensor(np.append(target_dir[:2], 0.0), dtype=torch.float,
                                 device=self._device).unsqueeze(0).unsqueeze(0)
            return np.asarray(self._agent.plan(state, lidar, dyn, tdir), float).reshape(-1)[:2]


class _Leg:
    def __init__(self, planner, target_dir):
        self._planner, self._target_dir, self._vel = planner, target_dir, np.zeros(2)

    def velocity(self, pos_xy, goal_xy, zone_rects):
        v = self._planner._plan(self._target_dir, self._vel, np.array(pos_xy, float), np.array(goal_xy, float),
                                zone_rects)
        self._vel = v.copy()
        return float(v[0]), float(v[1])
