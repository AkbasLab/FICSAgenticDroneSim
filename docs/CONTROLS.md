# Controls Manual

How to drive the platform: starting and stopping, flying from a script, and
flying by instruction. Condensed from *CarlaAir Command Reference v1.0*, whose
API tables were produced by introspecting the installed `carla` 0.9.16 and
`airsim` 1.8.1 modules.

> **This is the short version.** For synchronous mode and tick control, the road
> graph, weather, spawning traffic, sensors and perception, recording and replay,
> or the full API index, see the ten-part reference set in
> [`carlaair/`](carlaair/README.md).

Two clients, always. They talk to the same Unreal process on different ports and
neither knows about the other:

```python
import carla, airsim
world = carla.Client("127.0.0.1", 2000)              # the city
drone = airsim.MultirotorClient("127.0.0.1", 41451)  # the aircraft
```

CARLA owns the world, weather, ground vehicles, pedestrians and sensors. AirSim
owns the multirotor.

---

## 1. Starting and stopping

```powershell
cd D:\Research\CarlaAirSetup\CarlaAir-v0.1.7-Windows11-x86_64
.\CarlaAir.ps1 Town10HD
```

**Always launch through `CarlaAir.ps1`.** Double-clicking `CarlaUE4.exe` skips
the port setup, the AirSim bridge and the traffic generator.

| Option | Default | Effect |
|---|---|---|
| `[MAP]` | `Town10HD` | `Town01`–`Town05`, `Town10HD`, or an `_Opt` variant |
| `--res WxH` | 1280x720 | Window resolution |
| `--port PORT` | 2000 | CARLA RPC port |
| `--quality LEVEL` | Epic | `Low`, `Medium`, `High`, `Epic` |
| `--fg` | off | Keep the PowerShell session attached |
| `--kill` | — | Stop the last instance this script started |
| `--log` | — | Tail the log file |
| `--no-traffic` | off | Do not auto-start `auto_traffic.py` |
| `--traffic-vehicles N` | 30 | Vehicle count for auto traffic |
| `--traffic-walkers N` | 50 | Pedestrian count for auto traffic |
| `--package-root PATH` | — | Explicit `WindowsNoEditor` root |
| `--python PATH` | — | Explicit `python.exe` for auto traffic |

On a 4 GB card, `--quality Low --no-traffic` together make a large difference.
For measurement runs, `--no-traffic` also removes a confound.

```powershell
.\CarlaAir.ps1 --kill
```

---

## 2. Maps

| Map | Character | Load on 4 GB VRAM |
|---|---|---|
| `Town01` | Small town, river, bridges | light |
| `Town02` | Smaller town | light |
| `Town03` | Large urban, roundabout, tunnel | moderate |
| `Town04` | Highway loop, mountains | moderate |
| `Town05` | Squared grid, multi-lane | moderate |
| `Town10HD` | High-detail city centre | **heaviest** |

Each also ships as an `_Opt` variant supporting selective layer loading.

> **The map argument is not honoured at boot by this package.** The simulator
> always starts on `ServerDefaultMap` (Town10HD) and the requested town is
> discarded silently. The patched `CarlaAir.ps1` in the install works around it
> by switching with `load_world()` once the RPC port is up — watch for the
> `[Map]` line in the launch output, which is the authoritative statement of
> where you ended up. Full analysis: *CarlaAir Map Selection Fix v1.0*.

In-session switching works and destroys every actor:

```python
world = client.load_world("Town05")
```

---

## 3. The coordinate system — read this before writing flight code

**AirSim uses North-East-Down. Negative Z is up.** An altitude of 30 metres is
`z = -30`. A positive Z drives the aircraft into the ground. This is the single
most common error when writing flight code against this platform.

| Axis | Direction | Note |
|---|---|---|
| X | North / forward | Body-frame commands use forward |
| Y | East / right | `fly_left` is negative Y |
| Z | **Down** | **Altitude is negative** |

---

## 4. A minimal flight

```python
import airsim, time

client = airsim.MultirotorClient(ip="127.0.0.1", port=41451)
client.confirmConnection()

client.enableApiControl(True)
client.armDisarm(True)

client.takeoffAsync().join()
time.sleep(3)

# Body frame: vx is forward relative to the drone's heading.
client.moveByVelocityBodyFrameAsync(vx=3.0, vy=0, vz=0, duration=5.0).join()

# Velocity commands do not brake; they expire. Hover to stop.
client.hoverAsync().join()
client.landAsync().join()

client.armDisarm(False)
client.enableApiControl(False)
```

Two API behaviours worth internalising:

- **Velocity commands do not brake.** They apply for their duration and then
  stop being applied; the aircraft coasts. Follow one with `hoverAsync()` to
  stop.
- **The drone passes through the ground.** There is no terrain collision in this
  build, so landing cannot wait for a physical touchdown. Record the ground
  height before takeoff and descend back to it deliberately.

---

## 5. Flying by instruction

Two windows. Simulator first, agent once the map is visible:

```powershell
conda activate carlaAir
python baseline\open_loop_agent.py
```

The session runs as follows:

1. **How many drones?** — enter a number.
2. **Press Enter once the map has loaded.**
3. **What should Drone1 do?** — one plain-English instruction, repeated per drone.
4. Each plan is generated and **validated before anything arms**.
5. All drones launch together, one thread each.

The first plan of a session is slow — the model is loading into memory.
Subsequent plans are much faster, so record whether a run was cold or warm.

> Answering more than 1 **rewrites `settings.json` permanently** with that many
> drones, and the simulator boots with that count from then on. Restore it
> afterwards or the single-drone missions become invalid.

### The action set

The planner is restricted to exactly eight actions. Anything outside the set is
rejected by the schema before it reaches the aircraft.

| Action | Parameters | Meaning |
|---|---|---|
| `fly_to` | x, y, z | Fly to an absolute coordinate |
| `fly_straight` | duration | Forward, body frame |
| `fly_backward` | duration | Backward, heading held |
| `fly_left` | duration | Strafe left, heading held |
| `fly_right` | duration | Strafe right, heading held |
| `hover` | duration | Hold position |
| `set_altitude` | z | Climb or descend (**negative is higher**) |
| `land` | — | Controlled descent to recorded ground height |

| Constant | Value | Meaning |
|---|---|---|
| `ALTITUDE` | −8.0 | Default cruise height after takeoff |
| `SPACING` | 4.0 | Metres between drones at spawn |
| `MOVE_SPEED` | 5.0 | m/s for all directional moves |

**Speed is not expressible in an instruction.** No action takes a speed
parameter, so "fly fast" cannot be planned — it is a code change to
`MOVE_SPEED`, which also multiplies every distance, since legs are specified in
seconds.

### Why the JSON schema matters

The planner is constrained to `{"plan": [ ... ]}` — an *array* of steps, with
the action name restricted by an `enum`.

Without it, local models collapse multi-step requests into a single action:
asked to *hover for 3 seconds and then land*, both the 8B and 12B models
returned only the hover and dropped the landing. Prompt engineering, worked
examples and temperature reduction all failed; the schema fixed both models
immediately, and the `enum` stops the model inventing actions that do not exist.

**For constrained planning, output structure matters more than model size.**
That is the most transferable lesson in this stack, and it is why the study
measures schema-validity separately from correctness.

---

## 6. What the baseline agent cannot do

Design properties, not faults — and precisely what the research phases exist to
change.

| Capability | Status |
|---|---|
| Cameras | Configured at 1280×960 but **never read**. Not one `simGetImages` call exists in any agent script |
| Drone state | `getMultirotorState` is called twice — ground height and printing position — and is **never sent to the model** |
| The loop | The message list is system prompt, worked examples and your sentence. **Nothing from the simulator.** Execution is a flat `for` loop over a fixed plan |
| Obstacles | No avoidance of any kind. Fly above roof height |
| Vision | `llama3.2:3b` and `llama3.1:8b` have no vision encoder; images would not help them |

**The agent is blind, and it does not replan.** Removing that second property is
the point of Phase 5 onward.

---

## 7. Ports, paths and constants

| | |
|---|---|
| CARLA RPC | 2000 |
| CARLA Traffic Manager | 8000 |
| AirSim RPC | 41451 |
| Ollama | 11434 |
| Simulator root | `D:\Research\CarlaAirSetup\CarlaAir-v0.1.7-Windows11-x86_64` |
| conda environment | `D:\AllSetups\miniconda\envs\carlaAir` |
| Config AirSim reads | `<Documents known folder>\AirSim\settings.json` |
| Default cruise height | −8.0 m (NED, negative is up) |
| Drone spawn spacing | 4.0 m |
| Agent move speed | 5.0 m/s |
| Camera resolution | 1280×960 |

---

## 8. Diagnostics

| Symptom | Check |
|---|---|
| Simulator will not start | DirectX June 2010 runtime installed? See [`SETUP.md`](SETUP.md) §2 |
| Car-or-drone dialog appears | `SimMode: Multirotor` missing from `settings.json` |
| Drone count ignored | `settings.json` edited in the wrong Documents folder — see [`SETUP.md`](SETUP.md) §6 |
| Wrong town loaded | Read the `[Map]` line; see §2 above |
| Agent cannot connect | Simulator fully loaded? Ports 2000 and 41451 listening? |
| First plan very slow | Normal — the model is loading. Note the run as cold |
| Drone flies into the ground | Positive Z. Altitude is negative in NED |
| **Drones vibrate or hover oddly at start** | They spawned stacked inside each other and the physics is grinding them apart. `settings.json` spawn offsets are ignored by this build; separation happens at runtime. Restart, and let the agent place them |
| Drone will not move when repositioned | It is pinned inside another drone. Move the one on top away first — see `ensure_vehicles()` |
| Placement "succeeds" but drones are stacked | An old check read the vehicle-local frame, which can be 167 m wrong. Verify with `simGetVehiclePose` |

Full command and API reference: *CarlaAir Command Reference v1.0*
(`D:\Research\CarlaAirDocs\`).
