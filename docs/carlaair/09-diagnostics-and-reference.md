# Diagnostics and Reference

Symptoms and their causes, plus the ports, paths and constants worth keeping to hand.

> Part of the CarlaAir reference set — see [`README.md`](README.md) for the
> index. Generated from *CarlaAir Command Reference v1.0*; edit that manual and
> regenerate rather than editing this file.

---

## Diagnostics

```powershell
# Simulator process, memory and CPU
Get-Process CarlaUE4* | Select Name,Id,CPU,@{n='RAM_MB';e={[math]::Round($_.WorkingSet64/1MB)}}

# GPU memory
nvidia-smi --query-gpu=name,memory.total,memory.used --format=csv,noheader

# System memory actually available
(Get-Counter '\Memory\Available MBytes').CounterSamples[0].CookedValue

# Which Documents folder AirSim really reads
[Environment]::GetFolderPath('MyDocuments')

# The settings AirSim is using, straight from the server
conda run -n carlaAir python -c "import airsim; print(airsim.MultirotorClient().getSettingsString())"

# Which vehicles exist right now
conda run -n carlaAir python -c "import airsim; c=airsim.MultirotorClient(); c.confirmConnection(); print(c.listVehicles())"

# Which map is loaded
conda run -n carlaAir python -c "import carla; print(carla.Client('localhost',2000).get_world().get_map().name)"
```

| **Symptom** | **What to do** |
|---|---|
| Simulator frozen, one core at 100% | Either the spin bug, or a script left the world in synchronous mode. Check for a dead Python process first. **Do not** run a second script to probe it |
| `world.tick()` hangs | You are not in synchronous mode, or the traffic manager was not set to match |
| Vehicles stutter or teleport | Traffic manager not synchronised with the world. Call `tm.set_synchronous_mode(True)` |
| `RuntimeError: time-out` | Server not up yet, or `set_timeout()` too short. Try `client.set_timeout(20.0)` |
| `spawn_actor` raises | The spawn point is occupied. Use `try_spawn_actor`, or pick another point |
| Drone will not arm | `enableApiControl(True)` was not called, or another script holds control. Call `reset()` |
| Drone ignores commands | Wrong `vehicle_name`. Check `listVehicles()` |
| Images come back 256×144 | `settings.json` was not read — the OneDrive defect. See the setup guide |
| *couldn't reach the model* | `ollama list`, then `ollama pull`, or fix `MODEL` at line 14 |

## Ports, paths and constants

| CARLA RPC | 2000 |
|---|---|
| CARLA Traffic Manager | 8000 |
| AirSim RPC | 41451 |
| Ollama | 11434 |
| Simulator root | `D:-v0.1.7-Windows11-x86_64` |
| Agent scripts | `D:` |
| conda environment | `D:` |
| Config AirSim reads | `<Documents known folder>.json` |
| Default cruise height | -8.0 m (NED, negative is up) |
| Drone spawn spacing | 4.0 m |
| Agent move speed | 5.0 m/s |
| Camera resolution | 1280×960 |

### Document history

| **Version** | **Date** | **Notes** |
|---|---|---|
| 1.0 | 15 September 2026 | First edition. All API names verified by |
| introspection of the installed `carla` 0.9.16 and `airsim` 1.8.1 |  |  |
| modules. |  |  |

Slate
Companion volume to the *CarlaAir Setup Guide v1.0*

document
