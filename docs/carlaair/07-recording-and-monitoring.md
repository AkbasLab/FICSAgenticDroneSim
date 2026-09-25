# Recording, Debugging and Monitoring

Recording and replaying a run, drawing into the world for debugging, and watching logs while the simulator is running.

> Part of the CarlaAir reference set — see [`README.md`](README.md) for the
> index. Generated from *CarlaAir Command Reference v1.0*; edit that manual and
> regenerate rather than editing this file.

---

## Recording and replay

### CARLA recorder — records the whole world

```python
client.start_recorder("D:/Research/recordings/run01.log", True)   # True = also record sensors
# ... drive around ...
client.stop_recorder()

print(client.show_recorder_file_info("D:/Research/recordings/run01.log", True))
print(client.show_recorder_collisions("...run01.log", "a", "a"))
print(client.show_recorder_actors_blocked("...run01.log", 10, 1))

client.replay_file("D:/Research/recordings/run01.log", 0, 0, 0)   # start, duration, follow_id
client.set_replayer_time_factor(2.0)                              # 2x speed
client.stop_replayer()
```

### AirSim recording — records the drone

```python
c.startRecording()
print(c.isRecording())
c.stopRecording()
```

### The shipped recording demos

| **Script** | **Records** |
|---|---|
| `examples_record_demo/record_drone.py` | A drone flight |
| `examples_record_demo/record_vehicle.py` | A ground vehicle |
| `examples_record_demo/record_walker.py` | A pedestrian |
| `examples_record_demo/demo_director.py` | A scripted multi-actor scene |
| `examples_record_demo/trajectory_helpers.py` | Shared helper functions |

## Debug drawing

### AirSim overlays

```text
c.simPlotPoints([airsim.Vector3r(0,0,-20)], color_rgba=[1,0,0,1],
                size=25, duration=30, is_persistent=False)
c.simPlotLineStrip([airsim.Vector3r(0,0,-20), airsim.Vector3r(40,0,-20)],
                   color_rgba=[0,1,0,1], thickness=5, duration=30)
c.simPlotStrings(["waypoint 1"], [airsim.Vector3r(0,0,-20)],
                 scale=2, color_rgba=[1,1,0,1], duration=30)
c.simPlotArrows([...], [...])
c.simPlotTransforms([...])
c.simFlushPersistentMarkers()          # clear everything drawn
```

### CARLA debug helper

```text
d = world.debug
d.draw_point(carla.Location(x=10, y=20, z=5), size=0.2,
             color=carla.Color(255,0,0), life_time=20)
d.draw_string(carla.Location(x=10, y=20, z=6), "spawn A",
              draw_shadow=False, color=carla.Color(255,255,0), life_time=20)
d.draw_arrow(loc_a, loc_b, thickness=0.1, arrow_size=0.2, life_time=20)
d.draw_box(actor.bounding_box, actor.get_transform().rotation, 0.05,
           carla.Color(0,255,0), 20)
```

### Moving the spectator camera

```text
spec = world.get_spectator()
spec.set_transform(carla.Transform(carla.Location(x=0, y=0, z=60),
                                   carla.Rotation(pitch=-90)))

# Follow a vehicle from behind and above
tf = vehicle.get_transform()
spec.set_transform(carla.Transform(
    tf.location + carla.Location(z=25) - tf.get_forward_vector() * 12,
    carla.Rotation(pitch=-30, yaw=tf.rotation.yaw)))
```

### Unreal console commands

```text
c.simRunConsoleCommand("stat fps")
c.simRunConsoleCommand("stat unit")
c.simRunConsoleCommand("r.ScreenPercentage 70")
c.simRunConsoleCommand("t.MaxFPS 30")
```

## Logs, live monitoring and multi-window working

### What the launcher writes, and where

Every file below is created in the **install root**, beside
`CarlaAir.ps1`:

| **File** | **Contents** |
|---|---|
| `.carlaair.pid` | Process id of the simulator. `--kill` reads this |
| `.traffic.pid` | Process id of the traffic generator |
| `CarlaAir.log` | Unreal's log, requested via `-abslog` |
| `traffic.log` | Traffic generator **stdout** |
| `traffic.err.log` | Traffic generator **stderr** — see the warning below |

> **Important**
>
> **The traffic generator writes everything to stderr**
> On this installation `traffic.log` stays **0 bytes** and every line —
> including ordinary progress messages — lands in `traffic.err.log`. If you
> tail `traffic.log` you will watch an empty file forever and conclude the
> traffic generator is broken when it is working perfectly.
> 
> **Always tail `traffic.err.log`.**

Real output from a session on this machine:

```text
[Traffic] Connecting to CARLA (port 2000)...
[Traffic] Connected: Town10HD
[Traffic] Vehicles: 30/30 spawned
[Traffic] Walkers: 49/50 spawned with AI controllers
[Traffic] Traffic ready: 30 vehicles + 49 walkers on Town10HD
[Traffic] Running in background. Health checks every 10s.
[Traffic] Health: restarted 11 stalled vehicles
[Traffic] Health: restarted 16 stalled vehicles
```

> **Note**
>
> **"restarted N stalled vehicles" is normal**
> The generator health-checks every ten seconds and nudges vehicles that the
> traffic manager has wedged — typically at junctions. Seeing this every ten
> seconds is expected behaviour, not an error, despite arriving on stderr.
> Walkers spawning 49 of 50 is also normal: one spawn point was occupied.

### Live tailing

The launcher's own option:

```powershell
.\CarlaAir.ps1 --log
```

which is exactly `Get-Content CarlaAir.log -Wait -Tail 100`.

> **Careful**
>
> **`--log` throws if Unreal never wrote the file**
> It fails with *"No log file found"* when `CarlaAir.log` does not exist.
> On this installation the shipping build did not produce it despite
> `-abslog` being passed. If that happens, monitor `traffic.err.log` and
> the RPC ports instead — both are more informative anyway.

Tail anything, live, in its own window:

```powershell
Get-Content .\traffic.err.log -Wait -Tail 40

# Only the lines you care about
Get-Content .\traffic.err.log -Wait -Tail 0 | Where-Object { $_ -match "Health|Error|spawn" }

# Two logs in one window, prefixed
Get-Content .\traffic.err.log -Wait -Tail 10 | ForEach-Object { "[traffic] $_" }
```

### A four-window layout

This is the arrangement that works day to day.

| **Window** | **Purpose** | **Command** |
|---|---|---|
| 1 | Simulator | `..ps1 Town10HD` |
| 2 | Your script | `conda activate carlaAir` then `python ...` |
| 3 | Live log | `Get-Content ..err.log -Wait -Tail 40` |
| 4 | Resource watch | the loop in the next subsection |

Window 1 returns to a prompt once the simulator is up, because the launcher
starts the process detached and waits for both ports. Pass `--fg` only if
you want that window blocked and `Ctrl+C` to stop the simulator.

Open a second PowerShell already in the right place:

```powershell
Start-Process powershell -ArgumentList '-NoExit','-Command','cd D:\Research\AirSimRepo; conda activate carlaAir'
```

### Live resource monitoring

The numbers that matter on a 4 GB card, refreshed every two seconds:

```powershell
while ($true) {
  Clear-Host
  $gpu  = (nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu --format=csv,noheader)
  $ram  = [math]::Round((Get-Counter '\Memory\Available MBytes').CounterSamples[0].CookedValue/1024,1)
  $proc = Get-Process CarlaUE4-Win64-Shipping -ErrorAction SilentlyContinue
  $sim  = if ($proc) { "{0:N0} MB" -f ($proc.WorkingSet64/1MB) } else { "not running" }
  "GPU       : $gpu"
  "RAM free  : $ram GB"
  "Simulator : $sim"
  "Ollama    :"; ollama ps
  foreach ($p in 2000,41451,11434) {
    "  {0,-6} {1}" -f $p, $(if (Test-NetConnection 127.0.0.1 -Port $p -InformationLevel Quiet) {"up"} else {"down"}) }
  Start-Sleep 2
}
```

> **Note**
>
> **The spin bug has a specific signature**
> One CPU core pinned at 100%, **no** disk activity and **no** GPU
> activity, with the process alive and the ports open. A monitoring window makes
> this obvious within seconds, where otherwise it looks like a slow simulation.

### Frame rate and performance, live in the viewport

Unreal console commands, sent through the AirSim connection:

```text
c.simRunConsoleCommand("stat fps")        # frame rate overlay
c.simRunConsoleCommand("stat unit")       # frame, game, draw and GPU times
c.simRunConsoleCommand("stat gpu")        # GPU breakdown
c.simRunConsoleCommand("stat memory")     # memory overlay
c.simRunConsoleCommand("t.MaxFPS 30")     # cap the frame rate to free GPU
c.simRunConsoleCommand("r.ScreenPercentage 70")   # render at 70%, upscale
```

`stat unit` is the one to reach for: it tells you whether you are limited by
the game thread, the draw thread or the GPU, which decides whether lowering
quality will help at all.

Messages of your own, on screen:

```text
c.simPrintLogMessage("Mission phase: ", "search")
c.simPrintLogMessage("Waypoints remaining: ", str(n), severity=1)
```

### Recording a flight — what you actually get

```python
c.startRecording()
# ... fly ...
c.stopRecording()
print(c.isRecording())
```

Output lands in a timestamped folder under the **Documents known folder**
— the same OneDrive-redirected location AirSim reads its settings from:

```text
<Documents>\AirSim\2026-09-10-16-51-08\
    airsim_rec.txt
    images\img_Drone1__0_1789073468703600400.png
           img_Drone1__0_1789073468763762500.png
           ...
```

`airsim_rec.txt` is tab-separated, one row per captured frame:

| **Column** | **Meaning** |
|---|---|
| `VehicleName` | Which drone |
| `TimeStamp` | Milliseconds |
| `POS_X POS_Y POS_Z` | Position, NED — Z negative is up |
| `Q_W Q_X Q_Y Q_Z` | Orientation quaternion |
| `ImageFile` | Matching file in `images\` |

A real header and row from this machine:

```text
VehicleName  TimeStamp      POS_X    POS_Y     POS_Z     Q_W       Q_X       Q_Y        Q_Z        ImageFile
Drone1       1789073468475  196.787  -186.41   -43.5852  0.916333  0.145486  -0.0594222 -0.368289  img_Drone1__0_1789073468703600400.png
```

Rows arrive roughly every 50--60 ms, so about 20 Hz. Image filenames encode
vehicle, camera index and timestamp, so a row and its image are unambiguously
paired.

Reading a recording back:

```python
import csv
with open(r"C:\Users\you\OneDrive\Documents\AirSim\2026-09-10-16-51-08\airsim_rec.txt") as f:
    for row in csv.DictReader(f, delimiter="\t"):
        print(row["TimeStamp"], row["POS_X"], row["POS_Z"], row["ImageFile"])
```

> **Careful**
>
> Recording writes a PNG per frame at the configured resolution. At
> 1280×960 and 20 Hz that is roughly 1--2 GB per minute. Lower the capture
> resolution in `settings.json` before a long run, and remember the output
> folder is inside OneDrive, which will try to sync every frame.

### Recording the whole world instead

CARLA's recorder captures every actor, not just the drone, and replays
deterministically. It is the better tool when you care about traffic:

```python
client.start_recorder("D:/Research/recordings/run01.log", True)
# ...
client.stop_recorder()
print(client.show_recorder_file_info("D:/Research/recordings/run01.log", True))
client.replay_file("D:/Research/recordings/run01.log", 0, 0, 0)
```

|  | **AirSim recording** | **CARLA recorder** |
|---|---|---|
| Captures | One drone, plus images | Every actor's pose, every frame |
| Output | TSV + PNG sequence | One binary log |
| Replayable | No — it is data | **Yes**, in the simulator |
| Size | Very large (images) | Small |
| Good for | Training data, video | Reproducing a scenario |

### Logging from your own scripts

For anything you intend to analyse later, write structured events rather than
prose. One JSON object per line survives a crash, appends cheaply, and reads
straight into pandas:

```python
import json, time, pathlib

log = pathlib.Path("D:/Research/runs/run01.jsonl").open("a", buffering=1)

def event(kind, **fields):
    log.write(json.dumps({"t": time.time(), "kind": kind, **fields}) + "\n")

event("takeoff", drone="Drone1", z=-30)
event("waypoint_reached", drone="Drone1", index=3, pos=[x, y, z])
event("plan", drone="Drone1", model="llama3.2:3b", steps=6, seconds=7.1)
```

```python
import pandas as pd
df = pd.read_json("D:/Research/runs/run01.jsonl", lines=True)
```

> **Note**
>
> **Timestamp around the action, not the request**
> `execute_hover` in the agent scripts calls `hoverAsync().join()` and
> only then starts its timer, so wall-clock duration is always settling time plus
> the requested duration. Any timing you log must bracket the whole action —
> recording the *requested* duration will quietly understate every step.

### Recording an agent session

The agent scripts print everything you need — the instruction, the model's raw
output, each executed step — but they write **no log**. Capturing that
output is harder than it looks.

> **Important**
>
> **`Start-Transcript` does not capture Python's output**
> PowerShell's transcript records the shell's own output stream. A child process
> writing directly to the console is invisible to it. Running an agent under
> `Start-Transcript` produces a transcript containing the commands you typed
> and almost nothing else — verified on this installation, where four agent runs
> yielded four blank entries.

#### The quick way — pipe to a file

```powershell
python -u llama_airsim_agent.py 2>&1 | Tee-Object -FilePath D:\Research\runs\session-01.log
```

`-u` is not optional. Without it Python buffers stdout when it is piped, and
the prompts either appear late or not at all. `2>&1` folds stderr in, since
tracebacks go there.

This works, but interactive prompts can still render awkwardly because they
carry no trailing newline.

#### The reliable way — let the agent log itself

Fifteen lines inside the script beat any amount of console capture: the data is
structured, it survives a crash, and it appends across runs. Both
`user_prompt` and `raw` are already in scope inside
`interpret_user_prompt`, so the hook goes immediately after the raw output
is read.

Find this, near the `ollama.chat` call:

```text
        response = ollama.chat(
```

and put a timer before it:

```text
        _t0 = time.time()
        response = ollama.chat(
```

Then find:

```python
        raw = response["message"]["content"]
        print(f"  [model raw output] {raw}")
```

and append the log write:

```python
        try:
            with open(r"D:\Research\runs\agent-log.jsonl", "a", encoding="utf-8") as _f:
                _f.write(json.dumps({
                    "t": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "drone": self.vehicle_name,
                    "model": MODEL,
                    "instruction": user_prompt,
                    "raw_output": raw,
                    "plan_seconds": round(time.time() - _t0, 2),
                }) + "\n")
        except Exception as _e:
            print(f"  [log write failed: {_e}]")
```

`json` and `time` are already imported. The `try` wrapper matters:
a logging failure must never take down a flight.

#### Reading it back

```python
import pandas as pd
df = pd.read_json(r"D:\Research\runs\agent-log.jsonl", lines=True)
print(df[["t", "instruction", "plan_seconds"]])
```

Or from PowerShell:

```powershell
Get-Content D:\Research\runs\agent-log.jsonl | ForEach-Object { $j = $_ | ConvertFrom-Json; "{0}  {1,6:N1}s  {2}" -f $j.t, $j.plan_seconds, $j.instruction }
```

#### Cross-referencing with Ollama

The agent log tells you *what* was asked and produced. Ollama's server log
tells you what it cost. Together they give a complete picture of a run.

| **Source** | **What it gives you** |
|---|---|
| `agent-log.jsonl` | Instruction, raw model output, plan duration, model name |
| Ollama `server.log` | Per-request tokens, generation rate, prompt-cache hits, model loads, failures. Path: `%LOCALAPPDATA%.log` |
| `traffic.err.log` | The CARLA side — spawn counts, health checks |

The Ollama lines worth grepping:

```powershell
$L = "$env:LOCALAPPDATA\Ollama\server.log"

# per-request duration and status
Select-String $L -Pattern '^\[GIN\].*api/chat'

# tokens generated and generation rate
Select-String $L -Pattern 'print_timing.*eval time'

# how many tokens each request actually produced
Select-String $L -Pattern 'stop processing: n_tokens'
```

> **Note**
>
> **`stop processing: n_tokens` is the runaway detector**
> A normal plan totals roughly 500--650 tokens. A figure near `n_ctx_slot`
> — 4096 by default — means the model never stopped and generated until the
> context filled. On this installation one such request ran for 5 minutes
> 41 seconds and returned a 500. Capping `num_predict` turns that into a
> clean failure in well under a minute.

> **Careful**
>
> **Ollama rotates its log**
> Restarting Ollama renames `server.log` to `server-1.log` and pushes the
> others down, keeping five. Analyse a session before restarting the service, or
> check the numbered files for the window you want.

### Watching a run from a second Python process

Nothing stops a second client connecting while your main script flies. This is
the cheapest live telemetry there is:

```python
import airsim, time
c = airsim.MultirotorClient(); c.confirmConnection()

while True:
    for name in c.listVehicles():
        s = c.getMultirotorState(vehicle_name=name)
        p = s.kinematics_estimated.position
        v = s.kinematics_estimated.linear_velocity
        print("%-8s x=%7.1f y=%7.1f z=%7.1f  |v|=%5.1f  %s"
              % (name, p.x_val, p.y_val, p.z_val,
                 (v.x_val**2 + v.y_val**2 + v.z_val**2) ** 0.5, s.landed_state))
    time.sleep(0.5)
```

> **Careful**
>
> Read-only calls such as `getMultirotorState` are safe from a second
> process. Do **not** call `enableApiControl` or any movement command
> from a monitor — two processes contending for control produces behaviour that
> is very hard to diagnose. And if the simulator is already hung, do not attach a
> second client to investigate: it has historically made things worse rather than
> revealing anything.

### The launch arguments the launcher uses

Fixed by `CarlaAir.ps1`, for reference:

```text
CarlaUE4 <Map> -windowed -ResX=<w> -ResY=<h> -carla-rpc-port=<port>
         -quality-level=<level> -TexturePoolSize=2048 -unattended
         -nosound -UseVSync -abslog="<root>\CarlaAir.log"
```

> **Note**
>
> **`-windowed` is hard-coded**
> There is no fullscreen option on the launcher. Use `--res` at your display's
> native resolution for the nearest equivalent, or edit the script.
> `-TexturePoolSize=2048` is the streaming pool in megabytes and is the first
> thing to lower if the GPU runs out.

### A defect in the launcher's settings deployment

> **Important**
>
> **The launcher writes settings.json where AirSim will not read it**
> `CarlaAir.ps1` contains:
> 
> ```powershell
> $airsimSettingsDir = Join-Path $env:USERPROFILE "Documents\AirSim"
> Copy-Item $airsimSettingsSource $airsimSettingsTarget -Force
> ```
> 
> On a machine with OneDrive Known Folder Move — the Windows 11 default —
> AirSim reads `<OneDrive>.json`, while this copies
> to `C:\<you>.json`. The deployment
> is inert. Edits to `AirSimConfig.json` never reach the simulator,
> and the file AirSim does read is whatever was last put there by hand.

Until the launcher is fixed, deploy the configuration yourself after editing it:

```powershell
$src = "AirSimConfig\settings.json"
@([Environment]::GetFolderPath('MyDocuments'), (Join-Path $env:USERPROFILE "Documents")) |
  Select-Object -Unique | ForEach-Object {
    $d = Join-Path $_ "AirSim"
    New-Item -ItemType Directory -Force -Path $d | Out-Null
    Copy-Item $src (Join-Path $d "settings.json") -Force
    "deployed -> $d"
  }
```

The one-line fix in `CarlaAir.ps1` is to replace
`$env:USERPROFILE` with `[Environment]::GetFolderPath('MyDocuments')`
and drop the `"Documents"` segment.

### Housekeeping

```powershell
# Stale pid files after a hard kill
Remove-Item .\.carlaair.pid, .\.traffic.pid -ErrorAction SilentlyContinue

# Logs grow without bound -- rotate before a long session
Move-Item .\traffic.err.log ".\traffic.err.$(Get-Date -f yyyyMMdd-HHmmss).log"

# How much have the recordings taken?
Get-ChildItem "$([Environment]::GetFolderPath('MyDocuments'))\AirSim" -Directory |
  ForEach-Object { "{0,-24} {1,8:N1} MB" -f $_.Name,
    ((Get-ChildItem $_.FullName -Recurse -File | Measure-Object Length -Sum).Sum/1MB) }
```
