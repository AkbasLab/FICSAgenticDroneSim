# Simulator Control

Starting the simulator, stopping it, and controlling time inside it. Synchronous mode and tick control matter for experiments: a run that advances on wall-clock time is not reproducible.

> Part of the CarlaAir reference set — see [`README.md`](README.md) for the
> index. Generated from *CarlaAir Command Reference v1.0*; edit that manual and
> regenerate rather than editing this file.

---

## Shell and environment

### Activating the environment

| **Command** | **Purpose** |
|---|---|
| `conda activate carlaAir` | Enter the environment |
| `conda deactivate` | Leave it |
| `conda env list` | List all environments |
| `conda run -n carlaAir <cmd>` | Run one command without activating |
| `conda list -n carlaAir` | List installed packages |

### Checking the environment is sound

```powershell
# Imports and the decisive check that carla is a Windows build
conda run -n carlaAir python -c "import carla, airsim, pygame, numpy, cv2; print(carla.__file__)"

# Full stack self-test -- needs the simulator running
.\env_setup\TestEnv.ps1
```

### Are the servers up?

```powershell
foreach ($p in 2000,41451,11434) {
  "{0,-6} {1}" -f $p, $(if (Test-NetConnection 127.0.0.1 -Port $p -InformationLevel Quiet) {"LISTENING"} else {"closed"}) }
```

| **Port** | **Service** | **Provided by** |
|---|---|---|
| 2000 | CARLA RPC | the simulator |
| 8000 | CARLA Traffic Manager | the simulator |
| 41451 | AirSim RPC | the simulator |
| 11434 | Ollama | the Ollama background service |

## Starting and stopping

### Start

```powershell
cd D:\Research\CarlaAirSetup\CarlaAir-v0.1.7-Windows11-x86_64
.\CarlaAir.ps1 Town10HD
```

> **Careful**
>
> Always launch through `CarlaAir.ps1`. It sets the ports, brings up the
> AirSim bridge and starts the traffic generator. Double-clicking
> `CarlaUE4.exe` skips all of that.

### Every launcher option

| **Option** | **Default** | **Effect** |
|---|---|---|
| `[MAP]` | — | `Town01` … `Town05`, `Town10HD`, or an `_Opt` variant |
| `--res WxH` | 1280x720 | Window resolution |
| `--port PORT` | 2000 | CARLA RPC port |
| `--quality LEVEL` | — | `Low`, `Medium`, `High`, `Epic` |
| `--fg` | off | Keep the PowerShell session attached to the process |
| `--kill` | — | Stop the last instance this script started |
| `--log` | — | Tail the log file |
| `--no-traffic` | off | Do not auto-start `auto_traffic.py` |
| `--traffic-vehicles N` | 30 | Vehicle count for auto traffic |
| `--traffic-walkers N` | 50 | Pedestrian count for auto traffic |
| `--package-root PATH` | — | Explicit `WindowsNoEditor` root |
| `--python PATH` | — | Explicit `python.exe` for auto traffic |
| `--help` | — | Show usage |

### Useful combinations

```powershell
# Lightest possible -- best on a 4 GB card
.\CarlaAir.ps1 Town01 --quality Low --no-traffic

# Full city, heavy traffic
.\CarlaAir.ps1 Town10HD --traffic-vehicles 80 --traffic-walkers 120

# Large window, attached so Ctrl+C stops it
.\CarlaAir.ps1 Town03 --res 1920x1080 --fg

# Clean world for agent work: no traffic, nothing else moving
.\CarlaAir.ps1 Town05 --no-traffic --quality Medium
```

### Stop

| **Command** | **Effect** |
|---|---|
| `..ps1 --kill` | Stop the last instance the script started |
| `..bat` | Same thing, from Command Prompt |
| `Ctrl+C` | Works only if launched with `--fg` |
| `Stop-Process -Name CarlaUE4-Win64-Shipping -Force` | Last resort |

### Batch shims, for Command Prompt

The four `.bat` files are three-line wrappers that call the PowerShell
scripts with `-ExecutionPolicy Bypass`. Use them when you are not in
PowerShell:

| **Shim** | **Calls** |
|---|---|
| `StartCarlaAir.bat` | `CarlaAir.ps1` with your arguments |
| `StopCarlaAir.bat` | `CarlaAir.ps1 --kill` |
| `SetupEnv.bat` | `env_setup.ps1` |
| `TestEnv.bat` | `env_setup.ps1` |

### Logs

```powershell
.\CarlaAir.ps1 --log
```

## Pause, step and resume

There are **two independent ways** to freeze the simulation, and which one
you want depends on what you are doing.

|  | **AirSim pause** | **CARLA synchronous mode** |
|---|---|---|
| Freezes | The whole Unreal simulation | Advance only on your command |
| Good for | Inspecting a moment, debugging | Reproducible experiments, data collection |
| Granularity | Time or frames | One fixed timestep per tick |
| Determinism | No | **Yes** |

### AirSim: freeze everything

```python
import airsim
c = airsim.MultirotorClient()
c.confirmConnection()

c.simPause(True)            # freeze
print(c.simIsPause())       # -> True
c.simPause(False)           # resume
```

### AirSim: step forward while paused

```text
c.simPause(True)
c.simContinueForTime(0.5)     # run 0.5 s of simulated time, then pause again
c.simContinueForFrames(10)    # run exactly 10 frames, then pause again
```

> **Note**
>
> **This is the right tool for capturing a moment**
> Pause, fetch images or state, then step. Because nothing moves between the
> pause and the capture, every sensor reading belongs to the same instant.

### CARLA: synchronous mode — the deterministic route

```python
import carla
client = carla.Client("127.0.0.1", 2000); client.set_timeout(10.0)
world  = client.get_world()

settings = world.get_settings()
settings.synchronous_mode      = True      # the world advances only on tick()
settings.fixed_delta_seconds   = 0.05      # 20 simulated frames per second
world.apply_settings(settings)

# The traffic manager must agree, or vehicles desynchronise
tm = client.get_trafficmanager(8000)
tm.set_synchronous_mode(True)

for _ in range(200):
    world.tick()                # advance exactly one 0.05 s step
```

Returning to normal:

```python
settings = world.get_settings()
settings.synchronous_mode    = False
settings.fixed_delta_seconds = None
world.apply_settings(settings)
tm.set_synchronous_mode(False)
```

> **Important**
>
> **Always restore synchronous mode before your script exits**
> If a script leaves the server in synchronous mode and then dies, {the
> simulator freezes} — it is waiting for a `tick()` that will never arrive.
> It looks like a hang or a crash. Wrap the whole thing in
> `try / finally` and restore the settings in the `finally` block.

### Every world setting

| **Setting** | **Meaning** |
|---|---|
| `synchronous_mode` | World advances only on `tick()` |
| `fixed_delta_seconds` | Simulated seconds per step. `0.05` = 20 Hz |
| `no_rendering_mode` | Skip rendering entirely — much faster, big VRAM saving |
| `substepping` | Physics substeps for stability |
| `max_substeps` | Maximum substeps per frame |
| `max_substep_delta_time` | Largest substep |
| `actor_active_distance` | Beyond this, actors go dormant |
| `tile_stream_distance` | Large-map streaming radius |
| `max_culling_distance` | Render culling distance |
| `deterministic_ragdolls` | Reproducible pedestrian physics |
| `spectator_as_ego` | Treat the spectator camera as the ego vehicle |

> **Note**
>
> **On a 4 GB card, this pair is worth knowing**
> `no_rendering_mode = True` with `synchronous_mode = True` runs the
> simulation with no image output at all. For data collection that needs only
> positions and events, it is dramatically faster and frees almost all the VRAM.

### Resetting

```text
c.reset()                 # AirSim: drone back to its start pose
world = client.reload_world()   # CARLA: reload the current map, destroying all actors
```
