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
import time

import numpy as np

MAX_RAY_M = 4.0
DEBUG = [] if os.environ.get("NAVRL_DEBUG") == "1" else None   # per-tick record of what the planner decided (off unless NAVRL_DEBUG=1)
HRES_DEG = 10.0
V_ANGLES_DEG = [-10.0, 0.0, 10.0, 20.0]
MIN_RETURN_M = 0.35   # closer than this is the aircraft's own frame
# How NavRL is told the size of a moving obstacle (its width in 0.25 m steps, 0..3, and whether it is a tall column
# (0) or a low body). Its own demo code left both at zero, which reads as "no size": a parked drone was flown past
# at 1.1 m. A drone is the widest class and is flown round in the horizontal plane like a column.
PEER_WIDTH_CATEGORY = 3.0
POLICY_ACTION_LIMIT_MPS = 2.0   # the limit the pretrained policy was trained with (ppo.yaml, actor.action_limit)
SEPARATION_EASE_M = 2.0   # the separation filter starts easing the aircraft off this far outside the separation limit
SEPARATION_COAST_S = 0.8     # metres of coast per m/s of the aircraft's own speed (see keep_separation)
SEPARATION_PUSH_MPS = 1.0  # the most it pushes away from a peer that is already inside the limit
SEPARATION_PASS_MPS = 1.0  # most sideways speed it adds while closing on a peer, to the right of the line to it, so two aircraft that meet pass and do not stall
PEER_HEIGHT_CATEGORY = 0.0
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


def lidar_range_grid(points_flat, yaw, start_angle_deg, max_range=MAX_RAY_M, hres_deg=HRES_DEG,
                     v_angles_deg=V_ANGLES_DEG, first_row=1):
    """A real lidar scan as NavRL's input grid: (36 directions x 4 heights) of distance to the nearest return.

    `points_flat` is x, y, z, ... in the sensor frame (x forward, y right, z down); `yaw` turns them into the local
    frame the zones and the goal use. Direction h points at start_angle_deg + h * hres_deg (the goal direction at the
    start of the leg, as in NavRL's own ray function). The -10 degree row is left at max range, as NavRL's own
    harness does (it looks down and sees the ground when the aircraft is low), unless first_row=0: at cruise height the ground is
    out of range in that row, and it is the one that sees a ledge or slab just below the sensor. Distances are horizontal."""
    num_h = int(360 / hres_deg)
    grid = np.full((num_h, len(v_angles_deg)), float(max_range))
    pts = np.asarray(points_flat, float).reshape(-1, 3)
    if len(pts) == 0:
        return grid
    c, s = np.cos(yaw), np.sin(yaw)
    x = pts[:, 0] * c - pts[:, 1] * s
    y = pts[:, 0] * s + pts[:, 1] * c
    horiz = np.hypot(x, y)
    elev = np.degrees(np.arctan2(-pts[:, 2], horiz))
    az = np.degrees(np.arctan2(y, x))
    h_idx = np.rint(((az - start_angle_deg) % 360.0) / hres_deg).astype(int) % num_h
    v_arr = np.asarray(v_angles_deg, float)
    v_idx = np.abs(elev[:, None] - v_arr[None, :]).argmin(axis=1)
    ok = (np.abs(elev - v_arr[v_idx]) <= hres_deg / 2.0) & (horiz >= MIN_RETURN_M) & (v_idx >= first_row)
    for h, v, r in zip(h_idx[ok], v_idx[ok], horiz[ok]):
        if r < grid[h, v]:
            grid[h, v] = r
    return grid


def keep_separation(pos, vel, peer_positions, separation_m, real_speed=0.0):
    """The velocity with the part that closes on a peer taken out as it nears the separation limit.

    NavRL steers round another drone but only to about 1.5 m; the lab's rule is `separation_m`. Inside
    separation_m + SEPARATION_EASE_M the closing speed toward each peer is cut (all of it at the limit), inside the
    limit the aircraft is pushed away, and a sideways component to the right of the line to the peer is added while it
    is blocked, so two aircraft that meet go round each other and do not stand off."""
    v = np.array(vel, float)
    # the aircraft coasts about 0.8 m for every m/s of its own speed after its command is cut (measured live: 0.7, plus the command
    # tick), so the filter has to start that much earlier: the separation it holds is then the limit plus the coast
    coast = SEPARATION_COAST_S * real_speed
    for peer in peer_positions:
        offset = np.array(peer, float) - pos
        d = float(np.hypot(offset[0], offset[1]))
        if d < 1e-6 or d >= separation_m + coast + SEPARATION_EASE_M:
            continue
        n = offset / d
        coast_here = coast if float(np.dot(v, n)) > 0 else 0.0
        weight = min(1.0, (separation_m + coast_here + SEPARATION_EASE_M - d) / SEPARATION_EASE_M)
        closing = float(np.dot(v, n))
        if closing > 0:
            # the sideways nudge only while closing on the peer: always applied, it turned into a permanent orbit round a parked
            # drone that sat between the aircraft and its goal
            v = v + weight * min(SEPARATION_PASS_MPS, closing) * np.array([n[1], -n[0]])      # to the right of the way to the peer
            v = v - weight * closing * n
        if d < separation_m:
            v = v - n * min(SEPARATION_PUSH_MPS, 0.5 * (separation_m - d))
    return v


def nearest_ahead(points_flat, yaw, direction, half_angle_deg=30.0, max_range=12.0):
    """(distance, unit vector toward it) of the nearest lidar return in the way the aircraft is heading, or None.

    The cone is half_angle_deg either side of `direction`. Ground returns are left out (only elevations of -12 degrees and up; the
    ground is out of range there above about 2 m), as are returns closer than the aircraft's own frame."""
    pts = np.asarray(points_flat, float).reshape(-1, 3)
    if len(pts) == 0 or float(np.hypot(direction[0], direction[1])) < 1e-6:
        return None
    c, s = np.cos(yaw), np.sin(yaw)
    x = pts[:, 0] * c - pts[:, 1] * s
    y = pts[:, 0] * s + pts[:, 1] * c
    horiz = np.hypot(x, y)
    elev = np.degrees(np.arctan2(-pts[:, 2], horiz))
    heading = np.degrees(np.arctan2(direction[1], direction[0]))
    off = np.abs((np.degrees(np.arctan2(y, x)) - heading + 180.0) % 360.0 - 180.0)
    ahead = (off <= half_angle_deg) & (horiz >= MIN_RETURN_M) & (horiz <= max_range) & (elev >= -12.0)
    if not ahead.any():
        return None
    k = int(np.argmin(np.where(ahead, horiz, np.inf)))
    return float(horiz[k]), np.array([x[k], y[k]]) / float(horiz[k])


def speed_cap_from_scan(points_flat, yaw, direction, clear_m, divisor, half_angle_deg=30.0, max_range=12.0, floor_mps=0.4):
    """The speed the aircraft can still stop from, given the nearest lidar return in the way it is heading.

    The lidar reaches 12 m but the policy is only given 4 m. A real aircraft coasts about 0.7 m for every m/s of speed (measured
    live), so at 4.4 m/s it needs about 5 m to stop: cap = (distance - clear_m) / divisor. Returns inf when nothing is ahead."""
    hit = nearest_ahead(points_flat, yaw, direction, half_angle_deg, max_range)
    if hit is None:
        return float("inf")
    return max(floor_mps, (hit[0] - clear_m) / divisor)


def clear_ahead(grid, start_angle_deg, direction, rows, half_cells=3, hres_deg=HRES_DEG):
    """The nearest return in the lidar grid within +-half_cells directions (10 degrees each) of `direction`, over the given rows.
    The grid's direction h points at start_angle_deg + h * hres_deg; MAX_RAY_M means nothing within that range."""
    num_h = grid.shape[0]
    h0 = int(round(((np.degrees(np.arctan2(direction[1], direction[0])) - start_angle_deg) % 360.0) / hres_deg)) % num_h
    return float(min(grid[(h0 + k) % num_h, r] for k in range(-half_cells, half_cells + 1) for r in rows))


def apply_speed_floor(v, to_goal, dist, grid, start_angle_deg, floor_mps, rows, clear_m=MAX_RAY_M - 0.1):
    """The pretrained policy slows to a crawl in the last few metres before its goal even with nothing near (measured live: 0.1 m/s,
    3 m out, for 10 s). When nothing is within clear_m in the way it is heading, lift the speed to min(floor_mps, half the distance to
    the goal), keeping the policy's own direction; at the goal the floor tapers off, so the leg still ends there."""
    speed = float(np.hypot(v[0], v[1]))
    if floor_mps <= 0.0 or dist <= 0.3 or grid is None:
        return v
    target = min(floor_mps, 0.5 * dist)
    if speed >= target:
        return v
    if speed > 0.05:
        direction = np.array(v, float) / speed
    else:
        n = float(np.hypot(to_goal[0], to_goal[1]))
        if n < 1e-6:
            return v
        direction = np.array(to_goal, float) / n
    if clear_ahead(grid, start_angle_deg, direction, rows) < clear_m:
        return v
    return direction * target


class NavRLPlanner:
    """`scan_fn`, if given, returns (points_flat, yaw) from a real lidar; it is merged with the zone rays (the nearer of
    the two wins in every direction). One planner per aircraft when a scan_fn is used, because the scan belongs to one."""

    wants_adapter = True     # begin_leg is given the aircraft's adapter (see control/leg_planner_skill.py)
    fleet = None             # a FleetStates: with it, the other aircraft go into NavRL's moving-obstacle input
    separation_m = 0.0       # the lab's separation limit: NavRL alone keeps only ~1.5 m from another drone, so a filter holds this

    def __init__(self, navrl_dir=None, scan_fn=None):
        self.scan_fn = scan_fn
        self.navrl_dir = navrl_dir or os.environ.get("NAVRL_DIR") or DEFAULT_NAVRL_DIR
        self._lock = threading.Lock()   # one policy object shared by every drone's thread
        # the pretrained policy's action limit is 2.0 m/s; a faster limit scales its output (and so the velocity it is fed back)
        self.action_scale = float(os.environ.get("NAVRL_ACTION_LIMIT", POLICY_ACTION_LIMIT_MPS)) / POLICY_ACTION_LIMIT_MPS
        # speed governor (off unless NAVRL_GOVERNOR=1): caps the speed to what the aircraft can stop from in the distance the lidar sees
        self.governor = os.environ.get("NAVRL_GOVERNOR") == "1"
        self.gov_clear_m = float(os.environ.get("NAVRL_GOV_CLEAR", 1.5))
        self.gov_divisor = float(os.environ.get("NAVRL_GOV_DIV", 0.75))
        self.gov_binds = 0
        self.min_speed = float(os.environ.get("NAVRL_MIN_SPEED", 0.0))     # speed floor when nothing is ahead (0 = off), see apply_speed_floor
        self.max_speed = POLICY_ACTION_LIMIT_MPS * self.action_scale
        self.down_row = os.environ.get("NAVRL_DOWN_ROW") == "1"      # feed the policy the real -10 degree lidar row (see lidar_range_grid)
        self._tl = threading.local()     # the scan the last _plan call on this thread used
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

    def begin_leg(self, start_xy, goal_xy, adapter=None):
        """Starts one leg and returns a handle for it. The leg direction and last velocity live in the handle, not
        here, because one planner object is shared by every drone thread."""
        with self._lock:
            if not self._loaded:
                self._load()
        scan_fn = self.scan_fn or (getattr(adapter, "get_lidar_scan", None) if adapter is not None else None)
        peers_fn = (lambda: self.fleet.peers_of(adapter)) if (self.fleet is not None and adapter is not None) else None
        return _Leg(self, np.array(goal_xy, float) - np.array(start_xy, float), scan_fn, peers_fn, self.separation_m)

    def _plan(self, target_dir, vel, pos, goal, zone_rects, scan_fn=None, peers=None):
        with self._lock:
            torch = self._torch
            state = self._get_robot_state(pos, goal, vel, target_dir, device=self._device)
            start_angle = float(np.degrees(np.arctan2(target_dir[1], target_dir[0])))
            lidar, ranges, _ = self._navutils.get_ray_cast(
                pos, zone_rects, max_range=MAX_RAY_M, hres_deg=HRES_DEG, vfov_angles_deg=V_ANGLES_DEG,
                start_angle_deg=start_angle, device=self._device)
            self._tl.scan = None
            grid_now = np.array(ranges, float)
            if scan_fn is not None:
                scan = scan_fn()
                self._tl.scan = scan
                if scan is not None:
                    merged = np.minimum(ranges, lidar_range_grid(scan[0], scan[1], start_angle, first_row=0 if self.down_row else 1))
                    grid_now = merged
                    lidar = torch.tensor(MAX_RAY_M - np.maximum(merged, 0.1), dtype=torch.float,
                                          device=self._device).unsqueeze(0).unsqueeze(0)
            self._tl.grid = (grid_now, start_angle)
            tdir = torch.tensor(np.append(target_dir[:2], 0.0), dtype=torch.float,
                                 device=self._device).unsqueeze(0).unsqueeze(0)
            if peers:
                dyn = self._navutils.get_dyn_obs_state(pos, vel, [np.array(p, float) for p, _ in peers],
                                                       [np.array(v, float) for _, v in peers], tdir, device=self._device)
                present = dyn[..., 3] > 0           # the rows that hold a peer (padding rows are all zero)
                dyn[..., 8][present] = PEER_WIDTH_CATEGORY
                dyn[..., 9][present] = PEER_HEIGHT_CATEGORY
            else:
                dyn = torch.zeros((1, 1, 5, 10), dtype=torch.float, device=self._device)
            return np.asarray(self._agent.plan(state, lidar, dyn, tdir), float).reshape(-1)[:2]


class _Leg:
    def __init__(self, planner, target_dir, scan_fn=None, peers_fn=None, separation_m=0.0):
        self._planner, self._target_dir, self._vel, self._scan_fn = planner, target_dir, np.zeros(2), scan_fn
        self._peers_fn, self._separation_m = peers_fn, separation_m
        self._last_fix, self._speed_est = None, 0.0

    def _real_speed(self, pos_xy):
        """The aircraft's own speed over the last control ticks, from where it is (not from what was commanded)."""
        now = time.monotonic()
        speed = 0.0
        if self._last_fix is not None and now > self._last_fix[0]:
            speed = float(np.hypot(pos_xy[0] - self._last_fix[1], pos_xy[1] - self._last_fix[2])) / (now - self._last_fix[0])
            speed = 0.5 * speed + 0.5 * self._speed_est
        self._speed_est, self._last_fix = speed, (now, float(pos_xy[0]), float(pos_xy[1]))
        return speed

    def velocity(self, pos_xy, goal_xy, zone_rects):
        peers = self._peers_fn() if self._peers_fn else None
        # never more than the policy's own top speed: a position jump (a test stepping time, a telemetry glitch) is not a speed
        moving = min(self._real_speed(pos_xy), self._planner.max_speed)
        v = self._planner._plan(self._target_dir, self._vel, np.array(pos_xy, float), np.array(goal_xy, float),
                                zone_rects, self._scan_fn, peers)
        policy_v = v.copy()
        v = v * self._planner.action_scale
        v_scaled = v.copy()
        hit_d = None
        if self._planner.min_speed > 0.0 and getattr(self._planner._tl, "grid", None) is not None:
            grid, start_angle = self._planner._tl.grid
            rows = [0, 1, 2, 3] if self._planner.down_row else [1, 2, 3]
            v = apply_speed_floor(v, np.array(goal_xy, float) - np.array(pos_xy, float), float(np.hypot(goal_xy[0] - pos_xy[0], goal_xy[1] - pos_xy[1])),
                                  grid, start_angle, self._planner.min_speed, rows)
        # the velocity the policy is told it has: the real (scaled) one, or its own, in the units it was trained on
        self._vel = policy_v if os.environ.get("NAVRL_VEL_INPUT") == "policy" else v.copy()
        if self._planner.governor and getattr(self._planner._tl, "scan", None) is not None:
            scan = self._planner._tl.scan
            hit = nearest_ahead(scan[0], scan[1], v)
            if hit is not None:
                distance, toward = hit
                hit_d = distance
                cap = max(0.4, (distance - self._planner.gov_clear_m) / self._planner.gov_divisor)
                # only the part of the velocity that closes on the obstacle is cut, so the policy can still steer round it
                # (cutting all of it left an aircraft parked over a lamp post); moving faster than it can stop from, the
                # closing part goes to zero now, because the aircraft coasts about 0.7 m for every m/s of speed
                limit = 0.0 if moving > cap + 0.4 else cap
                closing = float(np.dot(v, toward))
                if closing > limit:
                    v = v - (closing - limit) * toward
                    self._planner.gov_binds += 1
        if peers and self._separation_m > 0:
            v = keep_separation(np.array(pos_xy, float), v, [p for p, _ in peers], self._separation_m, real_speed=moving)
        if DEBUG is not None:
            DEBUG.append((round(time.monotonic(), 2), [round(float(x), 1) for x in pos_xy], [round(float(x), 1) for x in goal_xy],
                          [round(float(x), 2) for x in policy_v], [round(float(x), 2) for x in v_scaled], [round(float(x), 2) for x in v],
                          round(float(moving), 2), None if hit_d is None else round(float(hit_d), 1)))
        return float(v[0]), float(v[1])
