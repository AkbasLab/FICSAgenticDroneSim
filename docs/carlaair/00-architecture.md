# Architecture and Integration

How CarlaAir is put together, and how to attach your own agents to it. Read this
before writing integration code; the rest of the reference set assumes the model
described here.

> Part of the CarlaAir reference set — see [`README.md`](README.md) for the
> index. This document is hand-written rather than generated from the manual.

---

## 1. One process, two servers

The single most important structural fact: **CARLA and AirSim are not separate
programs.** They are one Unreal Engine 4.26 process that hosts two independent
RPC servers, each with its own protocol, its own client library, and its own
view of the world.

```
                    CarlaUE4-Win64-Shipping.exe   (one process, one UE4 tick loop)
                    ┌──────────────────────────────────────────────┐
                    │  Unreal Engine 4.26                          │
                    │    ├── CARLA server plugin ──► RPC :2000     │
                    │    │     roads, weather, vehicles,           │
                    │    │     walkers, sensors, traffic manager   │
                    │    │                         └─► TM :8000    │
                    │    └── AirSim plugin ───────► RPC :41451     │
                    │          multirotor physics, flight API,     │
                    │          AirSim cameras                      │
                    └──────────────────────────────────────────────┘
                               ▲                        ▲
              carla (libcarla) │                        │ airsim (msgpack-rpc)
                               │                        │
        your script ───────────┴────────────────────────┘
                     │
                     └──► ollama :11434  (separate service, separate machine if you like)
```

Neither server knows about the other. A drone spawned through AirSim does not
appear in `world.get_actors()`, and a vehicle spawned through CARLA is invisible
to `simGetVehiclePose`. Anything that has to relate the two — "is the drone above
that car?" — is your code's job, comparing coordinates you fetched from both.

### The launch chain

```
CarlaAir.ps1                  sets ports, deploys settings.json, waits for both
  └── CarlaUE4.exe            thin shim; injects the project name as argv[0]
        └── CarlaUE4-Win64-Shipping.exe     the actual simulator
  └── auto_traffic.py         separate Python process, optional (--no-traffic)
  └── check_map.py            separate Python process, switches the map post-boot
```

Two consequences people trip over. The **boot map argument is ignored** by this
package — it always starts on `ServerDefaultMap` (Town10HD), which is why the
launcher switches afterwards over RPC. And **`settings.json` is read only at
process start**, so changing the vehicle roster means restarting the simulator,
not reconnecting.

---

## 2. Endpoints

| Port | Protocol | Served by | Client library |
|---|---|---|---|
| 2000 | CARLA RPC | the simulator | `carla` 0.9.16 (`libcarla.cp310-win_amd64.pyd`) |
| 8000 | Traffic Manager | the simulator | `carla`, via `client.get_trafficmanager(8000)` |
| 41451 | msgpack-rpc | the simulator | `airsim` 1.8.1 (`msgpack-rpc-python` 0.4.1, `tornado` 4.5.3) |
| 11434 | HTTP | Ollama service | `ollama` 0.6.2, or plain HTTP |

`--port` on the launcher moves the CARLA port only. The AirSim port is set in
`settings.json`, not on the command line.

Everything binds to `127.0.0.1` by default. Driving the simulator from another
machine means changing the AirSim `LocalHostIp`/`ApiServerPort` in
`settings.json` and passing `--carla-rpc-port` plus the right bind address to the
simulator — untested here, and worth a pilot before designing around it.

---

## 3. The Python side

Python **3.10** specifically: the CARLA wheel is `cp310`, so 3.11+ cannot import
it. The environment is conda-forge based; see
[`../SETUP.md`](../SETUP.md).

| Package | Version | Notes |
|---|---|---|
| `carla` | 0.9.16 | Compiled extension, installed from the wheel inside the CarlaAir archive. Not on PyPI for this build |
| `airsim` | 1.8.1 | Pure Python over msgpack-rpc. Calls `np.fromstring`, deprecated in NumPy 2 — works, but will break on NumPy 3 |
| `msgpack-rpc-python` | 0.4.1 | Pins `tornado` 4.5.3; do not upgrade tornado independently |
| `numpy` | 2.2.6 | CARLA's extension and OpenCV here are built against the NumPy 2 ABI. **Do not downgrade** |
| `ollama` | 0.6.2 | Thin client for the local model server |

### The two clients

```python
import carla, airsim

world_client = carla.Client("127.0.0.1", 2000)
world_client.set_timeout(10.0)           # raise on a slow machine; default is short
world = world_client.get_world()

drone = airsim.MultirotorClient("127.0.0.1", 41451)
drone.confirmConnection()
```

**Addressing differs, and this shapes multi-agent code.** CARLA hands you actor
objects with integer IDs, and you call methods on the actor. AirSim is
stateless-by-name: every call takes `vehicle_name=` and the client itself holds
no per-vehicle identity.

```python
drone.enableApiControl(True, vehicle_name="Drone2")
drone.takeoffAsync(vehicle_name="Drone2").join()
state = drone.getMultirotorState(vehicle_name="Drone2")
```

The vehicle names come from `settings.json` — `Drone1`, `Drone2`, … in this
project — and a name that is not in that file simply fails at call time.

---

## 4. Concurrency and determinism

### Async calls are futures

Every AirSim `*Async` method returns immediately with a future. `.join()` waits
for it. Fire several without joining and the vehicles move in parallel; that is
the whole mechanism behind multi-drone flight.

```python
futures = [drone.takeoffAsync(vehicle_name=n) for n in ("Drone1", "Drone2")]
for f in futures:
    f.join()                  # both climb together, then both are waited on
```

> **One client per thread — measured, not advised.** `msgpack-rpc-python`
> multiplexes one TCP socket over a tornado IOLoop that is not thread-safe.
> Sharing a single `MultirotorClient` across two drone threads failed on the
> first attempt, on both drones simultaneously:
>
> ```
> [Drone1] FAILED: RuntimeError: IOLoop is already running
> [Drone2] FAILED: BufferError: Existing exports of data: object cannot be re-sized
> ```
>
> Neither aircraft left the ground. Give every thread its own connection; they
> are cheap. Single-drone code will never show this, because one thread never
> contends.

> **`simAddVehicle` ignores the pose you give it.** A vehicle added to a running
> simulator appears at the player start regardless of the `Pose` argument —
> asked for `x=12`, measured `x=0`. Every runtime-spawned drone therefore
> stacks on whatever is already there, and two spawned this way came within
> **0.08 m** of each other in flight. Place them explicitly with
> `simSetVehiclePose` afterwards, then read the positions back and check them:
> nothing in this stack avoids collisions, so a silent placement failure puts
> aircraft on top of each other.
>
> ```python
> client.simAddVehicle("Drone2", "SimpleFlight", pose)        # pose ignored
> client.simSetVehiclePose(pose, ignore_collision=True,
>                          vehicle_name="Drone2")             # this one works
> ```
>
> Runtime vehicles get **no cameras** and do not survive a restart. They do
> survive `reset()`. Declare a persistent fleet in `settings.json` if you need
> cameras; otherwise spawning at runtime removes the restart entirely.

### Two different ways to stop time

| | AirSim pause | CARLA synchronous mode |
|---|---|---|
| Freezes | the whole Unreal simulation | advances only on your `tick()` |
| Determinism | no | **yes** |
| Use for | inspecting one instant | reproducible experiments |

```python
# deterministic stepping
settings = world.get_settings()
settings.synchronous_mode = True
settings.fixed_delta_seconds = 0.05          # 20 Hz
world.apply_settings(settings)
client.get_trafficmanager(8000).set_synchronous_mode(True)
try:
    for _ in range(200):
        world.tick()
finally:
    settings.synchronous_mode = False        # ALWAYS restore
    settings.fixed_delta_seconds = None
    world.apply_settings(settings)
```

**A script that dies while the server is in synchronous mode leaves the
simulator frozen**, waiting for a tick that never comes. It looks exactly like a
crash. Wrap it in `try/finally`.

> **Open question worth resolving before you design around it.** Both plugins
> share one UE4 tick loop, so CARLA synchronous mode plausibly gates AirSim
> physics too — but that has not been tested here, and the two APIs have no
> shared notion of time. If your experiment needs deterministic replay *of
> flight*, verify it: put the world in synchronous mode, issue a
> `moveByVelocityBodyFrameAsync`, and check whether the drone advances without
> `world.tick()`. Do not assume either answer.

---

## 5. Patterns for connecting agents

Four shapes, in increasing order of what they can express. Pick the smallest one
that answers your question.

### A · One process, one agent, one drone

The baseline. Straight-line code, trivially debuggable, no concurrency.

### B · One process, N threads, N drones

One thread per drone, each flying its own plan. Simple to write; all agents share
an address space, so "communication" between them is a variable, which is exactly
what makes it unsuitable for studying communication. See the thread-safety note
in §4.

### C · N processes, one agent each

Each agent is its own OS process with its own clients, talking to peers over a
transport you control — a socket, a queue, a broker. This is the shape that lets
you degrade communication honestly, because a message has to survive a real
channel. The cost is orchestration and log correlation.

### D · One process, N agents, explicit message bus

Agents are objects, but they may only interact through a bus you write, which can
drop, delay, duplicate and partition messages. Cheaper than (C) and far easier to
seed deterministically, while keeping the discipline of (C) — provided the bus is
the *only* path between agents.

> This project takes route (D), for the reason that makes it a research
> instrument rather than a convenience: **a seeded bus gives reproducible
> message loss.** Same seed, same dropped messages, same latency samples. See
> `AUV-07 — Inter-Agent Messaging` and `AUV-10 — Degraded Communications`.

### Attaching a language model

Nothing about the simulator cares that a model is involved. The pattern that
works on this hardware:

```python
import ollama
response = ollama.chat(
    model="llama3.2:3b",
    messages=[...],
    format=SCHEMA,                       # a JSON Schema, not a prose instruction
    options={"num_gpu": 0, "temperature": 0},
)
```

Three constraints that matter more than model choice. The GPU is **already spoken
for by the simulator**, so models run on CPU (`num_gpu: 0`) and compete for
system RAM. A **JSON schema with an action `enum`** is what stops small models
collapsing multi-step requests into one step — structure beats size here. And
model latency must never sit in a control loop: plan asynchronously, keep
low-level motion deterministic.

---

## 6. Ground truth versus belief

The simulator will happily tell an agent anything — every actor's exact position,
the full map, what the weather is about to be. **That is a hazard, not a
feature.** An agent that reads ground truth is not doing the task you think you
are measuring, and the failure is invisible in the results.

If you are building anything comparable to this study: give agents a belief state
fed only by their own sensing and received messages, and let the scenario manager
and evaluator hold the ground-truth handles. Enforce it structurally — an agent
object that has no reference to the world client cannot cheat, whatever anyone
writes later. `AUV-06` treats this as the rule that silently invalidates
everything if broken.

---

## 7. Constraints that shape designs here

| Constraint | Consequence for your design |
|---|---|
| 4 GB VRAM, simulator uses 2.6–3.2 GB | Models on CPU; large scenes and heavy traffic compete with rendering |
| 15.7 GB RAM | A 3B model co-resides comfortably; 8B needs everything else closed; 12B does not fit |
| No terrain collision | Landing cannot wait for touchdown — record ground height before takeoff |
| No obstacle avoidance anywhere | Separate drones by altitude and spawn spacing, or they will intersect |
| Velocity commands do not brake | Always follow with `hoverAsync()`, or the aircraft coasts |
| NED coordinates | Altitude is **negative**; a positive `z` flies into the ground |
| `settings.json` read at startup only | Changing the vehicle roster means restarting the simulator |
| Boot map argument ignored | Switch maps over RPC after the port opens |
| AirSim cameras configured but unused by the baseline | Image pipelines are unexercised here; budget time to validate them |

---

## 8. Where to look next

| Question | Document |
|---|---|
| How do I start, stop, pause or step the simulator? | [01 · Simulator Control](01-simulator-control.md) |
| What maps exist, and how do I query the road graph? | [02 · Maps and Navigation](02-maps-and-navigation.md) |
| How do I change weather, lighting, or inspect the scene? | [03 · World and Environment](03-world-and-environment.md) |
| How do I spawn and drive vehicles and pedestrians? | [04 · Actors and Traffic](04-actors-and-traffic.md) |
| What are the flight commands, and what is NED? | [05 · Drone Flight](05-drone-flight.md) |
| How do I get images and sensor data? | [06 · Sensors and Perception](06-sensors-and-perception.md) |
| How do I record a run or draw debug geometry? | [07 · Recording and Monitoring](07-recording-and-monitoring.md) |
| What ships with the build, and what does it not do? | [08 · Scripts and Limits](08-scripts-and-limits.md) |
| Something is broken — where do I start? | [09 · Diagnostics and Reference](09-diagnostics-and-reference.md) |
| Does method X exist in this build? | [10 · API Index](10-api-index.md) |

A worked example of all of this is `baseline/open_loop_agent.py`: connect,
schema-constrained planning, validation, thread-per-drone execution, native
JSONL logging.
