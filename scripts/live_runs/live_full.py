"""The full-map street scenario (configs/missions/full_map_001.json) flown live in CarlaAir: 6 drones, 6 sectors, 6 targets, 8 palms, zones.

Kept outside the repo. Run in the NavRL env with the sim client bridge:
    ~/run_navrl_py.sh live_large.py --tag L1 --profile medium_dynamic --leg-planner navrl --noclip off --overlay
Every drone is a CarlaAir vehicle (Drone1 is `SimpleFlight`); their start points and the lidar on each come from
~/Documents/AirSim/settings.json. One shared message bus, one guardian per drone, NavRL (or straight legs) flying every approved leg.
Zones are scheduled in mission time and stretched for the slow flier (k = 15 / 1.9), as in the mock study, so the two compare.
Writes ~/live_large_<tag>.json. Not recorded unless --record is given.
"""
import argparse
import json
import math
import os
import sys
import threading
import time

sys.path.insert(0, os.path.expanduser("~/FICSAgenticDroneSim"))
sys.path.insert(0, os.path.expanduser("~"))

from fics_drone.agents.persistent_agent import PersistentAgent
from fics_drone.coordination.message_bus import AgentLink, MessageBus
from fics_drone.core.scenario import load_scenario
from fics_drone.experiments.experiment_config import apply_zones
from fics_drone.simulator.airsim_adapter import AirSimVehicleAdapter

SCENARIO = os.path.expanduser("~/FICSAgenticDroneSim/configs/missions/full_map_001.json")
SAMPLE_S = float(os.environ.get("SAMPLE_S", 0.5))
VEHICLE = {"Drone1": "SimpleFlight"}      # every other drone has the vehicle name of its own


class TimedAdapter(AirSimVehicleAdapter):
    """Notes when each drone lands: after that its position estimate drifts and must not be read as a position."""
    landed = {}

    def land(self):
        TimedAdapter.landed[self.vehicle_name] = time.monotonic()
        return super().land()



if os.environ.get("LEAK_PROBE") == "1":
    import gc
    import collections

    def _rss_mb():
        with open("/proc/self/status") as f:
            for l in f:
                if l.startswith("VmRSS"):
                    return int(l.split()[1]) / 1024

    def _probe():
        base = collections.Counter(type(o).__name__ for o in gc.get_objects())
        while True:
            time.sleep(5)
            r = _rss_mb()
            print(f"PROBE rss {r:.0f} MB threads {threading.active_count()}", flush=True)
            if r > 1500:
                now = collections.Counter(type(o).__name__ for o in gc.get_objects())
                grow = sorted(((now[k] - base.get(k, 0), k) for k in now), reverse=True)[:12]
                print("PROBE over 1.5 GB; objects that grew most:", grow, flush=True)
                big = sorted(((len(o), type(o).__name__) for o in gc.get_objects() if isinstance(o, (list, dict, bytes, bytearray))), reverse=True)[:8]
                print("PROBE biggest containers (len, type):", big, flush=True)
                os._exit(4)
    threading.Thread(target=_probe, daemon=True).start()

parser = argparse.ArgumentParser()
parser.add_argument("--tag", required=True)
parser.add_argument("--profile", default="full_map_dynamic", choices=["full_map_none", "full_map_dynamic"])
parser.add_argument("--leg-planner", default="navrl", choices=["straight", "navrl"])
parser.add_argument("--speed", type=float, default=4.75, help="the flier's speed, for stretching zone times (as in the mock study)")
parser.add_argument("--cruise-height", type=float, default=12.0)
parser.add_argument("--leg-timeout", type=float, default=300.0)
parser.add_argument("--noclip", default="unrecorded")
parser.add_argument("--overlay", action="store_true")
parser.add_argument("--separation-margin", type=float, default=0.0, help="extra metres on the separation the filter holds, for hover jitter and sampling noise")
parser.add_argument("--record", action="store_true")
parser.add_argument("--only", default="", help="comma-separated drone names to fly (the others stay on the ground)")
args = parser.parse_args()

k = 15.0 / args.speed
scenario = apply_zones(load_scenario(SCENARIO), args.profile, 5.0 * k, 12.0 * k, 3.0 * k, 1.0 / k)
planner = None
if args.leg_planner == "navrl":
    from fics_drone.planners.navrl_planner import NavRLPlanner
    planner = NavRLPlanner()
FLOWN = [spec for spec in scenario.drones if not args.only or spec.name in args.only.split(",")]
adapters = {spec.name: TimedAdapter(VEHICLE.get(spec.name, spec.name)) for spec in FLOWN}
bus = MessageBus()
agents = {}
for spec in FLOWN:
    agents[spec.name] = PersistentAgent(adapters[spec.name], scenario, spec.sector, spec.spawn_offset, spec.battery_s,
                                        drone_name=spec.name, link=AgentLink(bus, spec.name), cruise_height=args.cruise_height,
                                        leg_planner=planner, leg_timeout_s=args.leg_timeout)
offsets = {s.name: s.spawn_offset for s in FLOWN}
if planner is not None:
    from fics_drone.planners.fleet_states import FleetStates
    planner.fleet = FleetStates(adapters, offsets)       # NavRL sees the other drones (peer state, as a swarm would broadcast it)
    planner.separation_m = scenario.min_separation_m + args.separation_margin     # and keeps the separation distance from them (as in the mock study)
t0 = time.monotonic()


def clock():
    first = next(iter(agents.values()))
    return first._live_elapsed()


stop = threading.Event()
if args.overlay:
    from zone_overlay import start_overlay
    start_overlay(scenario, clock, stop, positions_fn=lambda: [v for n, v in (samples[-1].items() if samples else []) if n != "t"])
stop_recording = None
if args.record:
    from run_recorder import start_recording
    stop_recording = start_recording(f"full_{args.tag}")

samples, collisions = [], []


def sampler():
    import airsim
    client = airsim.MultirotorClient()
    client.confirmConnection()
    last = {}
    while not stop.is_set():
        row = {"t": round(clock(), 2)}
        for name, adapter in adapters.items():
            try:
                x, y, z = adapter.get_position()
                ox, oy, _ = offsets[name]
                row[name] = (round(x + ox, 2), round(y + oy, 2), round(z, 2))
                info = client.simGetCollisionInfo(adapter.vehicle_name)
                if info.has_collided and info.time_stamp != last.get(name):
                    last[name] = info.time_stamp
                    collisions.append({"drone": name, "t": row["t"], "object": info.object_name, "xyz": row[name]})
            except Exception as exc:
                row[name] = None
        samples.append(row)
        time.sleep(SAMPLE_S)


threading.Thread(target=sampler, daemon=True).start()
reports = {}


def fly_one(name):
    reports[name] = agents[name].run()


threads = [threading.Thread(target=fly_one, args=(name,)) for name in agents]
wall0 = time.monotonic()
for t in threads:
    t.start()
for t in threads:
    t.join(timeout=1500)
stop.set()
time.sleep(0.6)
recording = stop_recording() if stop_recording else None

landed_at = {n: round(TimedAdapter.landed[VEHICLE.get(n, n)] - agents[n]._run_start, 1) if VEHICLE.get(n, n) in TimedAdapter.landed
             and agents[n]._run_start else None for n in agents}
trees, static_zones = scenario.obstacles, scenario.no_fly_zones
dynamic = [z for z in scenario.no_fly_zones if z.is_dynamic]
per_drone, in_tree, in_static, exposure, min_sep, min_tree = {}, 0, 0, 0.0, 1e9, 1e9
for name in agents:
    end = landed_at[name] if landed_at[name] is not None else 1e9
    track = [(r["t"], r[name]) for r in samples if r.get(name) and r["t"] <= end]
    for t, (x, y, z) in track:
        in_tree += any(tr.blocks_point(x, y, z) for tr in trees)
        in_static += any(zn.contains(x, y) for zn in static_zones if not zn.is_dynamic)
        exposure += SAMPLE_S * any(zn.contains(x, y, t) for zn in dynamic) / k
        if z > 3:
            min_tree = min(min_tree, min(math.hypot(x - tr.x, y - tr.y) for tr in trees))
    final = track[-1][1] if track else None
    rep = reports.get(name)
    per_drone[name] = {"final_xy": [final[0], final[1]] if final else None, "landed_at_s": landed_at[name],
                       "target_found": rep.target_found if rep else None,
                       "targets_sensed": list(rep.targets_sensed) if rep else None,
                       "targets_confirmed_by_self": list(rep.targets_confirmed_by_self) if rep else None,
                       "battery": round(rep.battery_frac_at_end, 2) if rep else None,
                       "guardian_failed_checks": sorted({c for e in agents[name].guardian_log.entries for c in e.failed_checks}),
                       "trace_tail": rep.trace[-6:] if rep else None,
                       "trace": rep.trace if rep else None}
for r in samples:
    pts = [(n, r[n]) for n in agents if r.get(n) and (landed_at[n] is None or r["t"] <= landed_at[n]) and r[n][2] > 3]
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            min_sep = min(min_sep, math.dist(pts[i][1], pts[j][1]))
found = sorted({r.target_found for r in reports.values() if r and r.target_found})
sensed = sorted({t for r in reports.values() if r for t in r.targets_sensed})
confirmed = sorted({t for r in reports.values() if r for t in r.targets_confirmed_by_self})
summary = {
    "tag": args.tag, "profile": args.profile, "leg_planner": args.leg_planner, "noclip_declared": args.noclip, "k": round(k, 2),
    "wall_s": round(time.monotonic() - wall0, 1), "targets_found_by_anyone": found, "targets_sensed_by_anyone": sensed, "targets_confirmed_by_anyone": confirmed,
    "samples_in_tree_keepout": in_tree, "samples_in_static_zone": in_static, "dynamic_zone_exposure_s_mock_eq": round(exposure, 2),
    "min_separation_m": round(min_sep, 2) if min_sep < 1e9 else None, "closest_to_a_trunk_m": round(min_tree, 1),
    "collisions_not_ground": [c for c in collisions if c["object"] != "SM_seaM"],
    "collision_records": len(collisions), "per_drone": per_drone, "recording": recording,
}
from fics_drone.planners import navrl_planner as _np
if _np.DEBUG is not None:
    json.dump({"t0_wall": wall0, "ticks": _np.DEBUG}, open(os.path.expanduser(f"~/live_full_{args.tag}_ticks.json"), "w"))
json.dump({**summary, "samples": samples, "collisions": collisions}, open(os.path.expanduser(f"~/live_full_{args.tag}.json"), "w"),
          default=str)
print(json.dumps(summary, indent=1, default=str))
