"""Live check of the overfly layer: Drone4 alone flies legs along the clear road x=-52 across a SYNTHETIC 20 m tree the agent is told about at (-52, -27) (the sim has no such tree).
Leg A: the agent chooses (detour or over). Leg B: back again with the detour planner switched off (forced 'no way round').
Writes ~/live_overfly_<tag>.json. Run: NAVRL_PROFILE=limit5 ~/run_navrl_py.sh live_overfly.py --tag O1"""
import argparse, json, math, os, sys, threading, time
from unittest import mock
sys.path.insert(0, os.path.expanduser("~/FICSAgenticDroneSim"))
sys.path.insert(0, os.path.expanduser("~"))
from fics_drone.agents import persistent_agent
from fics_drone.agents.persistent_agent import PersistentAgent
from fics_drone.coordination.message_bus import AgentLink, MessageBus
from fics_drone.core.scenario import load_scenario
from fics_drone.planners.navrl_planner import NavRLPlanner
from fics_drone.simulator.airsim_adapter import AirSimVehicleAdapter
from fics_drone.control.skills import take_off

ap = argparse.ArgumentParser()
ap.add_argument("--tag", required=True)
ap.add_argument("--A", default="-52,5")
ap.add_argument("--B", default="-52,-59")
args = ap.parse_args()
TREE = (-52.0, -27.0, 2.0, 20.0)
scenario = load_scenario(os.path.expanduser("~/FICSAgenticDroneSim/configs/missions/full_map_001.json"))
from fics_drone.core.obstacles import TreeObstacle
scenario.obstacles = list(scenario.obstacles) + [TreeObstacle(x=TREE[0], y=TREE[1], z_bottom=2.0, z_top=TREE[3], trunk_r=TREE[2], crown_r=TREE[2], crown_from_frac=1.0)]
spec = next(d for d in scenario.drones if d.name == "Drone4")
ox, oy, _ = spec.spawn_offset
adapter = AirSimVehicleAdapter("Drone4")
planner = NavRLPlanner()
bus = MessageBus()
agent = PersistentAgent(adapter, scenario, spec.sector, spec.spawn_offset, spec.battery_s, drone_name="Drone4",
                        link=AgentLink(bus, "Drone4"), cruise_height=12.0, leg_planner=planner, leg_timeout_s=300.0)
samples, stop = [], threading.Event()
t0 = time.monotonic()

def sampler():
    import airsim
    client = airsim.MultirotorClient(); client.confirmConnection()
    while not stop.is_set():
        try:
            x, y, z = adapter.get_position()
            info = client.simGetCollisionInfo("Drone4")
            samples.append((round(time.monotonic() - t0, 2), round(x + ox, 2), round(y + oy, 2), round(z, 2), bool(info.has_collided)))
        except Exception:
            pass
        time.sleep(0.5)
threading.Thread(target=sampler, daemon=True).start()

def leg(name, target_world, force_no_way_round):
    a = time.monotonic(); i0 = len(samples); trace = []
    tgt = (target_world[0] - ox, target_world[1] - oy, 12.0)
    if force_no_way_round:
        with mock.patch.object(persistent_agent, "plan_around", return_value=None):
            event = agent._guarded_fly(tgt, trace)
    else:
        event = agent._guarded_fly(tgt, trace)
    seg = samples[i0:]
    return {"leg": name, "event": event.value, "seconds": round(time.monotonic() - a, 1), "trace": trace,
            "max_z": max((s[3] for s in seg), default=None), "min_z": min((s[3] for s in seg), default=None),
            "closest_to_trunk_axis_m": round(min((math.hypot(s[1] - TREE[0], s[2] - TREE[1]) for s in seg), default=0), 1),
            "samples_inside_tree": sum(1 for s in seg if math.hypot(s[1] - TREE[0], s[2] - TREE[1]) < TREE[2] and s[3] < TREE[3]),
            "collision_samples": sum(1 for s in seg if s[4]), "final": list(seg[-1][1:4]) if seg else None}

A = tuple(float(v) for v in args.A.split(",")); B = tuple(float(v) for v in args.B.split(","))
out = []
take_off(adapter)
agent.belief.position = adapter.get_position()
out.append(leg("go_to_A", A, False))
out.append(leg("A_to_B_forced_over", B, True))
out.append(leg("B_to_A_agent_chooses", A, False))
out.append(leg("A_to_B_agent_chooses", B, False))
agent._guarded_fly((0.0, 0.0, 12.0), [], purpose="home")
stop.set(); time.sleep(0.6)
res = {"tag": args.tag, "tree": TREE, "legs": out, "samples": samples}
json.dump(res, open(os.path.expanduser(f"~/live_overfly_{args.tag}.json"), "w"))
print(json.dumps({"legs": out}, indent=1))
