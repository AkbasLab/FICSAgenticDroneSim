# Shipped Scripts and Known Limits

The example scripts that come with the build, the agent layer that sits on top, and an explicit list of what this build does not do.

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

## The LLM agent layer

### Ollama

| **Command** | **Purpose** |
|---|---|
| `ollama --version` | Check it is installed |
| `ollama list` | Models on disk |
| `ollama ps` | Models loaded now, and on CPU or GPU |
| `ollama pull llama3.2:3b` | Download a model |
| `ollama stop <model>` | Unload from memory immediately |
| `ollama rm <model>` | Delete from disk |
| `ollama run <model>` | Interactive chat, for testing the model alone |
| `ollama show <model>` | Parameters, context length, licence |

> **Note**
>
> **`ollama ps` is the diagnostic that matters**
> It shows `PROCESSOR` as `100% CPU` or `100% GPU`. For this
> installation it must read CPU — the agents pass `num_gpu: 0` so the
> simulator keeps all 4 GB of VRAM. A model resident for five minutes after its
> last call is normal; `ollama stop` frees it at once.

### Running an agent

Two terminals. Simulator in the first, agent in the second:

```powershell
conda activate carlaAir
cd D:\Research\AirSimRepo

python test_flight.py            # deterministic, no LLM -- prove the stack works
python llama_airsim_agent.py     # natural language, local model
python mistral_airsim_agent.py   # natural language, larger local model
python gemini_airsim_agent.py    # natural language, Google cloud (needs a key)
```

| **Script** | **Planner** | **Notes** |
|---|---|---|
| `test_flight.py` | none | Takeoff, forward, land. Run this first |
| `test_fly_forward.py` | none | Minimal forward flight |
| `move_to_coord.py` | none | Absolute coordinate move |
| `give_coords.py` | none | Print current position |
| `llama_airsim_agent.py` | Ollama, local | Model set at line 14 |
| `mistral_airsim_agent.py` | Ollama, local | Larger, slower |
| `gemini_airsim_agent.py` | Google cloud | Needs `.env` and an API key |
| `Multiple.py` | — | Thread-per-drone coordinator, imported by the agents |

### Changing the model

```powershell
cd D:\Research\AirSimRepo
(Get-Content llama_airsim_agent.py -Raw) -replace 'MODEL = "llama3.2:3b"','MODEL = "llama3.1:8b"' | Set-Content llama_airsim_agent.py -Encoding utf8
```

### Tunable constants

At the top of each agent script:

| **Constant** | **Default** | **Effect** |
|---|---|---|
| `ALTITUDE` | -8.0 | Cruise height after takeoff |
| `SPACING` | 4.0 | Metres between drones at spawn |
| `MOVE_SPEED` | 5.0 | m/s for all directional moves. **The only way to change speed** — no action exposes it |
| `MODEL` | model name | Which Ollama model plans |

### The eight actions the planner may use

| **Action** | **Parameters** | **Meaning** |
|---|---|---|
| `fly_to` | x, y, z | Fly to an absolute coordinate |
| `fly_straight` | duration | Forward, body frame |
| `fly_backward` | duration | Backward, heading held |
| `fly_left` | duration | Strafe left |
| `fly_right` | duration | Strafe right |
| `hover` | duration | Hold position |
| `set_altitude` | z | Climb or descend (negative is higher) |
| `land` | — | Descend to the recorded ground height |

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
