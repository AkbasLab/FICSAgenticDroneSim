# Baseline Environment — `v0.1-open-loop-baseline`

**Phase 1 deliverable** · Version 1.0 · Frozen 2026-09-18
**Vault reference:** `AUV-02 — Baseline Freeze`

This records the exact system in which the open-loop baseline was measured.
Every value was read from the machine, not transcribed from documentation.

---

## 1. What "baseline" means here

The tag `v0.1-open-loop-baseline` denotes the system in which:

- each drone receives a **separate** natural-language instruction;
- the language model generates a **complete action list before takeoff**;
- plans are **validated** before any vehicle arms;
- drones execute **concurrently**, one thread each;
- **no replanning occurs after launch.**

That last property is the one the project exists to remove. Everything from
Phase 5 onward is aimed at it.

---

## 2. Hardware

| | |
|---|---|
| CPU | 12th Gen Intel Core i5-12500H — 12 physical / 16 logical cores |
| RAM | 15.7 GB |
| GPU | NVIDIA GeForce RTX 3050 Laptop — 4096 MiB VRAM |
| GPU driver | 581.95 |

**These figures are load-bearing, not incidental.** The 4 GB VRAM forces
language models onto the CPU (`num_gpu: 0`), and 15.7 GB of system RAM bounds
which models can co-reside with the simulator. See §8.

---

## 3. Operating system and runtime

| | |
|---|---|
| OS | Microsoft Windows 11 Home Single Language 10.0.26200, 64-bit |
| Shell | Windows PowerShell 5.1.26100 |
| Python | **3.10.21**, 64-bit |
| Interpreter | `D:\AllSetups\miniconda\envs\carlaAir\python.exe` |
| Conda environment | `carlaAir`, created from **conda-forge** with `--override-channels` |
| Package manager | Miniconda at `D:\AllSetups\miniconda` |

conda-forge was used deliberately to avoid the Anaconda commercial Terms of
Service gate. Everything after environment creation comes from PyPI.

### Legacy DirectX runtime — required

Unreal Engine 4.26 links seven legacy DirectX libraries that Windows 11 does not
ship. Without them the simulator refuses to start. Install the **DirectX
End-User Runtime (June 2010)** from microsoft.com before anything else.

`XINPUT1_3.dll` · `X3DAudio1_7.dll` · `XAPOFX1_5.dll` · `XAUDIO2_7.dll`
`D3DCOMPILER_43.dll` · `d3dx9_43.dll` · `d3dcsx_43.dll`

---

## 4. Simulator

| | |
|---|---|
| Product | CarlaAir **v0.1.7** |
| Components | CARLA 0.9.16 + AirSim 1.8.1 in one Unreal Engine 4.26 process |
| Install root | `D:\Research\CarlaAirSetup\CarlaAir-v0.1.7-Windows11-x86_64` |
| Source | GitHub release tag `v0.1.7-win11-x86_64` (4 parts, reassembled) |
| Map used for baseline | **Town10HD** |
| Ports | CARLA 2000 · CARLA Traffic Manager 8000 · AirSim 41451 |

### Archive hashes

Reassembled archive — 6,688,810,915 bytes:

```
b1e71ae81efa6446ac770c64a26c0814f3af1fab60ea719470cc0a0743035c1f  CarlaAir-v0.1.7-Windows11-x86_64_release.zip
```

Parts as downloaded:

```
e31b16858600a37f7d50da114d57671b5775b847acde6f917203973a07fc86f6  ...zip.part001
4852a9fc920d6ee67aedd5b400861eca855a66e3bd55761e39e0c511dc07c6b5  ...zip.part002
17c1d18ae31af0dd723e704d84bf96114d56d595751316b0513265e8bddb1ac1  ...zip.part003
36482a60eaa9b882d4511f0f0bf4c0e738f4d0089c1a54cfa9c41f55d36507da  ...zip.part004
```

Verifying the reassembled archive against the first hash reproduces the exact
simulator binary, which pins the Unreal build, the maps and the CARLA Python
wheel in one step.

---

## 5. AirSim configuration

AirSim reads `settings.json` from the **Windows Documents known folder**. With
OneDrive Known Folder Move enabled — the Windows 11 default — that is
`%USERPROFILE%\OneDrive\Documents\AirSim\settings.json`, *not*
`%USERPROFILE%\Documents\AirSim\settings.json`.

| | |
|---|---|
| Path | `C:\Users\<user>\OneDrive\Documents\AirSim\settings.json` |
| SHA-256 | `59e6d9b7a7135c200333737d94ff5f884693f24615610947a6f5c64078d97fec` |
| SettingsVersion | 1.2 |
| SimMode | `Multirotor` |
| Vehicles | `Drone1` |
| VehicleType | `SimpleFlight` |
| Cameras | `"0"` and `"front_center"`, both 1280 × 960 |

`SimMode: Multirotor` is what suppresses the car-or-drone dialog at launch.
Omitting the key restores it.

> **Known defect in the launcher.** `CarlaAir.ps1` deploys `settings.json` to
> `$env:USERPROFILE\Documents\AirSim` — the folder AirSim does *not* read on a
> OneDrive-redirected profile. Its deployment is therefore inert on this
> machine, and the file above must be maintained by hand. Read only at process
> start; changing it requires restarting the simulator.

---

## 6. Python packages

Full manifests are committed alongside this document:

- `requirements.txt` — 43 packages, `pip freeze` from the frozen environment
- `environment.yml` — conda environment export, no build strings

Load-bearing versions:

| Package | Version |
|---|---|
| `carla` | 0.9.16 (`libcarla.cp310-win_amd64.pyd`) |
| `airsim` | 1.8.1 |
| `numpy` | 2.2.6 |
| `opencv-python` / `opencv-contrib-python` | 5.0.0.93 |
| `pygame` | 2.6.1 |
| `pillow` | 12.3.0 |
| `msgpack-rpc-python` | 0.4.1 |
| `msgpack-python` | 0.5.6 |
| `tornado` | 4.5.3 |
| `ollama` | 0.6.2 |
| `pydantic` | 2.13.5 |

> **`requirements.txt` is not portable as generated.** The `carla` entry is a
> local file URL into the CarlaAir install. On another machine, install the
> wheel from that machine's own extracted archive:
>
> ```
> pip install <install-root>\PythonAPI\carla\dist\carla-0.9.16-cp310-cp310-win_amd64.whl
> ```
>
> Wheel SHA-256: `f255c0fa2c89cdbd7b194546a45c03be45009033e4fece8c7021d13d9727fc33`

> **Do not downgrade NumPy.** The CARLA extension module and OpenCV 5 here are
> both built against the NumPy 2 ABI. Note that `airsim` 1.8.1 calls
> `np.fromstring` (`utils.py` lines 15 and 18), deprecated in NumPy 2 and
> removed in NumPy 3 — both decode paths were verified working but will need
> patching before any NumPy 3 upgrade.

---

## 7. Language models

| | |
|---|---|
| Runtime | Ollama **0.34.1** (baseline measurements taken on 0.34.0) |
| Endpoint | `http://127.0.0.1:11434` |
| Model store | `D:\AllSetups\Ollama\models` via `OLLAMA_MODELS` (User scope) |
| `OLLAMA_KEEP_ALIVE` | 5m0s (default) |
| `OLLAMA_NUM_PARALLEL` | 1 |
| `OLLAMA_MAX_LOADED_MODELS` | 0 (auto) |

### Local models

| Model | Manifest SHA-256 | Weights digest | Size |
|---|---|---|---|
| `llama3.2:3b` | `a80c4f17acd55265feec403c7aef86be0c25983ab279d83f3bcd3abbcb5b8b72` | `sha256:dde5aa3fc5ffc17176b5e8bdc82f587b24b2678c6c66101bf7da77af9f7ccdff` | 1.88 GB |
| `llama3.1:8b` | `46e0c10c039e019119339687c3c1757cc81b9da49709a3b3924863ba87ca666e` | `sha256:667b0c1932bc6ffc593ed1d03f895bf2dc8dc6df21db3042284a6f4416b06a29` | 4.58 GB |

### Cloud model

| | |
|---|---|
| Identifier | `gemini-flash-latest` |
| Status | **Not used in the baseline.** Requires an API key and sends data off-machine |

`gemini-flash-latest` is a moving tag and therefore unsuitable for a frozen
baseline. If the Gemini arm is ever used for results, pin a dated model id.

### Inference options at baseline

```python
options = {"num_gpu": 0, "temperature": 0, "num_predict": 512, "num_thread": 12}
format  = PLAN_SCHEMA       # JSON schema requiring {"plan": [ ... ]}
```

| Option | Why |
|---|---|
| `num_gpu: 0` | **Required.** The simulator holds 2.6–3.2 GB of 4 GB VRAM; no useful model fits alongside it |
| `temperature: 0` | Greedy decoding for repeatability |
| `num_predict: 512` | Caps runaway generation. Without it one observed request generated 4,007 tokens against a 4,096 context and failed after 5 m 41 s |
| `num_thread: 12` | Ollama defaults to 8 on this CPU. Improves prompt evaluation ~50%; generation ~5% |

> **`seed` is not set at baseline.** Greedy decoding gives repeatability in
> practice, but `seed` is the explicit control and must be set before any run
> whose reproducibility is claimed in the paper. This is a known gap, carried
> into Phase 14.

---

## 8. Measured performance at baseline

`llama3.2:3b`, CPU-only, simulator running, Town10HD:

| | |
|---|---|
| Model load (cold) | ~6 s |
| First plan of a session | 16.8 s (483 prompt tokens, cold cache) |
| Subsequent plans | **2.9 – 3.7 s** (18–21 new prompt tokens, cache hit) |
| Generation rate | 14.4 – 15.8 tokens/s |
| Prompt evaluation rate | 54 – 67 tokens/s |
| Resident memory | ~1.9 GB (618 MiB model + 1,299 MiB repack) |
| Context | 4,096 tokens |

Ollama's prompt cache holds the system prompt and few-shot examples across
invocations, which is why only the first plan of a session is slow.

### Memory budget

| Model | RAM loaded | Runs alongside the simulator? |
|---|---|---|
| `llama3.2:3b` | ~2.6 GB | Yes, comfortably |
| `llama3.1:8b` | ~5.5 GB | Only with browsers closed |
| `mistral-nemo` (12B) | ~7.5 GB | **No** |

---

## 9. Baseline code

**The baseline agent is written from scratch for this project.** No third-party
agent code is used, referenced at runtime, or vendored.

### The decision, and why

An earlier version of this document pinned the baseline to an external
repository, `niranjanpillai2009-altr/AirSimRepo` at commit `e2b297d`, which
declares **no licence**. Without an explicit licence, default copyright applies:
no right to redistribute, and no right to create derivative works.

That made it a publication blocker rather than a footnote, since Phase 20
releases a public research artifact. Two exits existed — obtain a licence grant
from the author, or reimplement independently. **On 2026-09-24 the project chose
to reimplement**, and the external code was removed from this repository's
history entirely.

| | |
|---|---|
| Baseline agent | `baseline/open_loop_agent.py` — original to this project |
| Licence | Ours to set; settled in `AUV-21` before publication |
| External code used | **None** |

### What carries over, and what does not

Facts, APIs and findings are not copyrightable; specific code is. The following
are carried across as **specification**, and implemented independently:

- the eight-action plan vocabulary (`fly_to`, `fly_straight`, `fly_backward`,
  `fly_left`, `fly_right`, `hover`, `set_altitude`, `land`);
- the open-loop property itself — plan before takeoff, validate, execute
  concurrently, never replan;
- the finding that a JSON schema with an action `enum` fixes multi-step
  collapse in small local models;
- the NED convention and the Windows known-folder behaviour, both properties of
  AirSim and Windows rather than of anyone's code.

The prior benchmark figures quoted in `BASELINE_MISSIONS.md` (`llama3.1:8b`
scoring 0/3 on M05, 3/3 on M06, 1/3 on M07) remain **citations of that project's
published results**, attributed as such, and are not measurements of this one.

---

## 10. Startup procedure

Exactly as run for the baseline.

**Window 1 — simulator:**

```
cd D:\Research\CarlaAirSetup\CarlaAir-v0.1.7-Windows11-x86_64
.\CarlaAir.ps1 Town10HD --no-traffic --quality Low
```

Wait until the map is visible, not merely until the prompt returns. Confirm:

```
foreach ($p in 2000,41451,11434) {
  "{0,-6} {1}" -f $p, $(if (Test-NetConnection 127.0.0.1 -Port $p -InformationLevel Quiet) {"up"} else {"down"}) }
```

**Window 2 — agent:**

```
conda activate carlaAir
python baseline\open_loop_agent.py
```

Then: drone count → Enter once the map has loaded → one natural-language
instruction per drone.

**Shutdown:**

```
.\CarlaAir.ps1 --kill
```

### Environment variables set on this machine

| Variable | Value | Scope |
|---|---|---|
| `OLLAMA_MODELS` | `D:\AllSetups\Ollama\models` | User |

No other project-specific variables are set. `conda` is configured with
`auto_activate: false` so it does not disturb other Python installations.

---

## 11. Known defects present at baseline

Recorded so they are not mistaken for regressions later.

| Defect | Effect |
|---|---|
| `CarlaAir.ps1` deploys `settings.json` to the wrong Documents folder | Configuration edits do not reach the simulator; must be copied manually |
| `-abslog` produces no file | `.\CarlaAir.ps1 --log` fails with *"No log file found"* |
| Traffic generator writes to **stderr** | `traffic.log` stays 0 bytes; all output is in `traffic.err.log` |
| `/tmp/` screenshot paths in `drone_car_chase.py` and `demo_drive_and_fly.py` | The **C** key throws on Windows |
| `execute_hover` starts its timer *after* `hoverAsync().join()` | Wall-clock hover exceeds the requested duration by the settling time — an unlogged offset in every timed action |
| Agent scripts write no log of their own | Instructions and plans are not recorded. Being fixed in Phase 1.3 |
| Drone passes through terrain | No collision; landing descends to a height recorded before takeoff |
| No yaw action in the agent action set | Lateral moves strafe; the aircraft never turns |

---

## 12. Change log

| Date | Change |
|---|---|
| 2026-09-18 | v1.0 — baseline frozen. All values read from the machine. |
