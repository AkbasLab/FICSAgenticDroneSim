# Shipped Scripts and Known Limits

The example scripts that come with the build, and an explicit list of what this build does not do.

The manual's *LLM agent layer* section is deliberately **not** included: it documents a third-party agent this project does not use. The agent layer for this study is [`../../baseline/`](../../baseline/).

> Part of the CarlaAir reference set — see [`README.md`](README.md) for the
> index. Generated from *CarlaAir Command Reference v1.0*; edit that manual and
> regenerate rather than editing this file.

---

## Running the shipped scripts

```powershell
conda activate carlaAir
cd D:\Research\CarlaAirSetup\CarlaAir-v0.1.7-Windows11-x86_64
python examples\aerial_surveillance.py --help
```

| **Script** | **Options** | **Shows** |
|---|---|---|
| `examples/aerial_surveillance.py` | 6 | Drone camera sweep over the city |
| `examples/city_tour.py` | 5 | Scripted camera tour |
| `examples/data_collector.py` | 7 | Writing sensor data to disk |
| `examples/demo_drive_and_fly.py` | 6 | Ground vehicle and drone together |
| `examples/drone_car_chase.py` | 4 | Drone tracking a moving vehicle |
| `examples/fly_drone_keyboard.py` | 0 | Manual keyboard flight |
| `auto_traffic.py` | 4 | Populating the city with traffic |

All of them accept `--help`. Run that first — the option names differ
between scripts.

## What this build does *not* include

Worth knowing before you go looking for something that is not there.

| **Absent** | **Detail** |
|---|---|
| `agents` navigation package |  |
| `import agents` fails — `BasicAgent`, `BehaviorAgent`, |  |
| `GlobalRoutePlanner` and `LocalPlanner` are **not installed**. |  |
| Only `PythonAPI/carla/dist` ships, not the `agents` source. Use the |  |
| traffic manager for autonomous driving, or write route following yourself on |  |
| top of waypoints (Section 5) |  |
| Stock CARLA example scripts |  |
| `manual_control.py`, `generate_traffic.py`, `tutorial.py` and the |  |
| rest of the upstream `PythonAPI/examples` folder are not in this build. |  |
| The twelve scripts that *are* present are listed in Section 17 |  |
| The numbered guide tutorials |  |
| `01_hello_world` through `08_full_showcase` exist in the CarlaAir |  |
| *source* repository under `CarlaAir_Release/guide/examples/`, not in |  |
| this binary release |  |
| Terrain collision for the drone |  |
| The multirotor passes through the ground. Landing must descend to a height |  |
| recorded before takeoff |  |
| A yaw action in the LLM agents |  |
| The agent action set strafes without turning. `rotateToYawAsync` exists in |  |
| the API but no agent action exposes it |  |
| Obstacle avoidance |  |
| Nothing in this stack avoids buildings. `simCreateVoxelGrid` and |  |
| `cast_ray` give you the raw material to build it |  |
| Perception in the LLM agents |  |
| Cameras are configured but never read; the model receives no simulator state. |  |
| See the setup guide |  |

### Getting the missing navigation agents

If you need `BasicAgent` or `BehaviorAgent`, take the `agents`
folder from a matching CARLA 0.9.16 source tree and place it on the Python path
beside your scripts. It is pure Python and has no compiled component, so it
works with the wheel installed here.
