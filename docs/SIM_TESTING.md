# Flying Phases 3–7 in CARLA-Air

Running the same code in the real simulator. Work down this in order — each
step depends on the one before it, so if step 2 fails there is no point trying
step 5.

Budget about **60–90 minutes** for a full pass. Record video as you go; several
of these runs are the demo footage.

> Mock runs (`docs/TESTING.md`) prove the *logic*. These runs prove the
> **flight**. If a phase passes on the mock but fails here, the problem is in
> the simulator, the adapter, or the environment — not the agent.

---

## 0. Bring the environment up

**One time per boot:**

1. Launch CARLA-Air and wait for Town10HD to finish loading. Don't rush this —
   commands sent during load fail in confusing ways.
2. Open PowerShell:

```powershell
conda activate carlaAir
cd path\to\AgenticDroneSimRepo
python -c "import sys; print(sys.executable)"
```

The path **must** contain `envs\carlaAir`. If it doesn't, the environment isn't
active and every import will fail against the wrong Python.

3. Confirm `settings.json` declares Drone1–4:

```powershell
type $env:USERPROFILE\Documents\AirSim\settings.json
```

If it doesn't, generate it and **restart CARLA-Air** (settings are only read at
startup):

```powershell
python -c "from agentic_uav.simulator.scenario_manager import write_airsim_settings; print(write_airsim_settings(4))"
```

### Checkpoint 0 — connection

```powershell
python -c "import airsim; c=airsim.MultirotorClient(); c.confirmConnection(); print(c.listVehicles())"
```

Expect `['Drone1', 'Drone2', 'Drone3', 'Drone4']`.

**If this fails, stop.** Nothing below will work. Check the sim is fully loaded
and that port 41451 is free.

---

## 1. Phase 3 — Skills in the real world

**What you're checking:** the skill layer drives real flight, and four drones
fly concurrently without interfering.

### 1a. Single drone, all skills

```powershell
python scripts\phase3_showcase.py --adapter airsim
```

**Watch for:**
- takeoff climbs to about 8 m and holds
- the search sweep flies clean parallel lanes, not a scribble
- **landing settles on the ground and stops** — it should not sink through the
  terrain or stop several metres up. This is the behaviour that took the most
  work to get right; it's the thing to check most carefully.

**Pass:** every skill reports `SUCCESS`, drone ends on the ground, disarmed.

### 1b. Four drones at once

```powershell
python scripts\phase3_demo.py --adapter airsim
```

**Watch for:** all four lift off within a second or two of each other and fly to
*different* waypoints simultaneously.

**Pass:** four drones airborne at the same time, no two swapping speeds or
stalling. If they take turns or behave erratically, that's the AirSim client
threading issue — each vehicle must get its own `MultirotorClient`.

**Reset between runs:** if drones end up in a bad state, restart CARLA-Air.
That's faster than debugging a wedged vehicle.

---

## 2. Phase 4 — The canonical mission

**What you're checking:** the scripted baseline flies the whole mission and the
evaluator scores real flight.

```powershell
python scripts\run_canonical_mission.py --airsim
```

Takes several minutes — four sectors get swept.

**Watch for:** each drone sweeping its own quadrant, then all returning to base
and landing.

**Pass:** `MISSION SUCCESS` with all 8 criteria PASS.

**If coverage is below 95%:** the drones flew but drifted off their lanes.
Check whether `moveToPositionAsync` is timing out — real flight is slower than
the mock, and `LEG_TIMEOUT` may need raising for the sim.

**Good footage:** this is your best top-down demo shot. Pull the camera up to
see all four sweep patterns at once.

---

## 3. Phase 5 — Persistent agent, real flight

**What you're checking:** the closed loop works when skills take real time and
can really fail.

### 3a. Normal task

```powershell
python scripts\run_persistent_agent.py --airsim
```

**Pass:** `TASK COMPLETE`, and the decision trace shows each objective chosen
*after* the previous skill reported success — the same event→objective pattern
as the mock, but now the timings are real.

### 3b. Low battery — the important one

```powershell
python scripts\run_persistent_agent.py --airsim --battery 45
```

Battery is measured in **real seconds** here, so pick a value shorter than the
mission takes. Start with 45; if it still completes, halve it.

**Pass:** `TASK ABORTED SAFELY` — you should *watch it change its mind mid-air*,
break off the search, and come home. That moment is the single best thing to put
on video: the drone visibly deciding, not following a script.

### 3c. Different sector

```powershell
python scripts\run_persistent_agent.py --airsim --sector S3
```

**Pass:** `TASK COMPLETE` with `detections: ['T2']` — it found a different
target because it searched a different place.

---

## 4. Phase 6 — Belief and knowledge gaps

**What you're checking:** the audit trail reflects real flight.

```powershell
python scripts\run_persistent_agent.py --airsim --log --log-json sim_run.json
```

**Pass:** each decision prints KNEW / DID NOT KNOW / DECIDED, with **real
timestamps** rather than zeros. Confirm `battery` actually falls across steps —
that exercises the adapter clock and is the thing that was previously missing.

Check the gaps shrink: early steps say "no targets observed yet"; after the
sweep, the target appears under `targets`.

Keep `sim_run.json` — a real-flight belief trace is good evidence for a writeup.

---

## 5. Phase 7 — Four agents talking mid-flight

**What you're checking:** the fleet coordinates over the message bus during
real, concurrent flight.

```powershell
python scripts\run_team_mission.py --airsim --messages
```

This uses the **threaded** runner: one thread and one AirSim client per drone,
so they genuinely fly at the same time.

**Watch for:**
- all four airborne simultaneously, each in its own sector
- in the message log, sends and deliveries interleaved *between* drones — not
  drone 1's entire conversation followed by drone 2's

**Pass:** all four `COMPLETE`, heartbeats and status updates delivered, and
`TEAM SUCCESS`.

Then check knowledge actually spread:

```powershell
python scripts\run_team_mission.py --airsim --beliefs
```

**Pass:** a drone whose sector contains no target still lists both targets, and
they're recorded as second-hand — it learned them from `TARGET_FOUND` messages
sent by teammates while everyone was in the air.

> Note: this run is **not deterministic** — thread scheduling varies, so message
> counts differ between runs. That's expected in the sim. Use the mock
> (`run_team_mission.py` with no flag) whenever you need a reproducible number.

---

## Recording checklist

If you're capturing footage while you do this, the shots worth having:

| Shot | Command | Why |
|---|---|---|
| 4 drones lifting off together | `phase3_demo.py --adapter airsim` | shows real concurrency |
| Top-down sweep of all 4 sectors | `run_canonical_mission.py --airsim` | best hero image |
| Drone aborting on low battery | `run_persistent_agent.py --airsim --battery 45` | shows autonomy, not scripting |
| Terminal beside the sim | any `--log` run | ties decisions to flight |

Grab stills for `docs/images/` while you're here — see `docs/images/README.md`
for the list the README expects.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Vehicle API for Drone1 not available` | drones not in `settings.json` | regenerate settings, restart CARLA-Air |
| Only one drone moves at a time | using the sequential runner | `--airsim` selects the threaded one; confirm you passed it |
| Drone sinks through the ground | ground level not recorded pre-takeoff | it's captured in `takeoff()`; ensure takeoff ran before land |
| Everything times out | sim still loading, or paused | wait for Town10HD, check the sim window has focus/is running |
| `No module named airsim` | wrong Python | `conda activate carlaAir`, verify `sys.executable` |
| Battery never drops | adapter clock missing | `AirSimVehicleAdapter.now()` must exist (it does as of Phase 7) |
| Drones drift / miss waypoints | real flight slower than mock | raise `LEG_TIMEOUT` in `search_policy.py` / `mission_runner.py` |

When a run wedges, restarting CARLA-Air is almost always faster than debugging
the vehicle state.
