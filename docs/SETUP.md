# Setup Guide

Everything needed to go from a bare Windows 11 machine to a flying drone that
takes plain-English instructions. Condensed from *CarlaAir Setup Guide v1.0*
and `BASELINE_ENVIRONMENT.md`; both record more detail and the reasoning behind
each choice.

**Order matters.** Each step depends on the one before it. The DirectX runtime
in particular must be installed before the simulator is first launched.

---

## 1. Hardware

| | Minimum used here | Note |
|---|---|---|
| CPU | Intel Core i5-12500H, 12 physical / 16 logical cores | `num_thread: 12` in the agent matches this |
| RAM | 15.7 GB | Bounds which models can co-reside with the simulator |
| GPU | RTX 3050 Laptop, **4 GB VRAM** | The simulator alone uses 2.6–3.2 GB |
| Disk | ~25 GB | 6.7 GB archive plus the extracted build |

**The 4 GB VRAM figure is load-bearing, not incidental.** It is why language
models run on the CPU (`num_gpu: 0`) and compete for system RAM rather than
video memory, and it is why the factorial experiments are planned against a
mock adapter rather than live AirSim.

---

## 2. DirectX End-User Runtime (June 2010) — first

Unreal Engine 4.26 links seven legacy DirectX libraries that Windows 11 does not
ship. Without them the simulator refuses to start, with an error that does not
name the real cause.

```
XINPUT1_3.dll   X3DAudio1_7.dll   XAPOFX1_5.dll   XAUDIO2_7.dll
D3DCOMPILER_43.dll   d3dx9_43.dll   d3dcsx_43.dll
```

Install the **DirectX End-User Runtime (June 2010)** from microsoft.com. It
installs alongside modern DirectX and does not replace it.

---

## 3. The simulator

CarlaAir v0.1.7 — CARLA 0.9.16 and AirSim 1.8.1 inside one Unreal Engine 4.26
process. Released as four archive parts that must be reassembled.

**Verify before extracting.** The reassembled archive is 6,688,810,915 bytes:

```powershell
Get-FileHash .\CarlaAir-v0.1.7-Windows11-x86_64_release.zip -Algorithm SHA256
```

```
b1e71ae81efa6446ac770c64a26c0814f3af1fab60ea719470cc0a0743035c1f
```

Per-part hashes are in `BASELINE_ENVIRONMENT.md` §4. Verifying this one hash
pins the Unreal build, every map and the CARLA Python wheel in a single step —
which is most of what reproducibility requires.

Extract to a path without spaces. The reference install is:

```
D:\Research\CarlaAirSetup\CarlaAir-v0.1.7-Windows11-x86_64
```

---

## 4. Miniconda and PowerShell

Install Miniconda, then allow local scripts and initialise conda for PowerShell:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
conda init powershell
```

Open a new PowerShell window afterwards — `conda activate` does not work in the
window where `conda init` ran.

---

## 5. The Python environment

```powershell
conda env create -f environment.yml
conda activate carlaAir
```

Python is **3.10.21**, built from conda-forge with `--override-channels`,
deliberately avoiding the Anaconda commercial Terms of Service gate.

### The one package that is not portable

`requirements.txt` is a `pip freeze` of the measured environment, and its
`carla` entry is a **local file URL** into this machine's install. On any other
machine, install that wheel from your own extracted archive:

```powershell
pip install <carlaair-root>\PythonAPI\carla\dist\carla-0.9.16-cp310-cp310-win_amd64.whl
```

Wheel SHA-256: `f255c0fa2c89cdbd7b194546a45c03be45009033e4fece8c7021d13d9727fc33`

### Do not downgrade NumPy

The CARLA extension module and OpenCV here are both built against the NumPy 2
ABI. Note that `airsim` 1.8.1 calls `np.fromstring` (`utils.py` lines 15 and
18), deprecated in NumPy 2 and removed in NumPy 3 — both decode paths work
today but will need patching before any NumPy 3 upgrade.

---

## 6. `settings.json` — where AirSim actually reads it

AirSim reads `settings.json` from the Windows **Documents known folder**. With
OneDrive Known Folder Move — the Windows 11 default — that is:

```
%USERPROFILE%\OneDrive\Documents\AirSim\settings.json
```

**not** `%USERPROFILE%\Documents\AirSim\`.

> **Known launcher defect.** `CarlaAir.ps1` deploys its template to
> `$env:USERPROFILE\Documents\AirSim` — the folder AirSim does *not* read on a
> redirected profile. Its deployment is inert here, so this file must be
> maintained by hand. The baseline agents work around the same trap with
> `documents_dir()`, which asks Windows via `SHGetFolderPathW` instead of
> assuming.

Required keys: `SettingsVersion 1.2`, `SimMode: Multirotor`, one `SimpleFlight`
vehicle. `SimMode: Multirotor` is what suppresses the car-or-drone dialog at
launch; omitting it brings the dialog back. Expected SHA-256 and full contents
are in `BASELINE_ENVIRONMENT.md` §5.

**It is read only at process start.** Changing it means restarting the
simulator.

---

## 7. Ollama and the local models

| | |
|---|---|
| Runtime | Ollama 0.34.x, endpoint `http://127.0.0.1:11434` |
| Model store | Set `OLLAMA_MODELS` (User scope) if you keep models off C: |
| Primary model | `llama3.2:3b` — 1.88 GB |
| Secondary | `llama3.1:8b` — 4.58 GB, needs other applications closed |

```powershell
ollama pull llama3.2:3b
ollama list
```

Manifest and weight digests for both models are recorded in
`BASELINE_ENVIRONMENT.md` §7. A 12B model does not fit alongside the simulator
on 15.7 GB.

The cloud model `gemini-flash-latest` is **not used in the baseline**: it needs
an API key, sends data off-machine, and is a moving tag, which disqualifies it
from a frozen baseline.

---

## 8. Verify the whole stack

Start the simulator, then run the shipped self-test:

```powershell
.\CarlaAir.ps1 Town10HD --no-traffic --quality Low
```

```powershell
.\env_setup\TestEnv.ps1
```

It checks imports, a live CARLA connection on 2000 and a live AirSim connection
on 41451, and reports a PASS / FAIL / WARN tally.

For a first flight and the day-to-day commands, continue to
[`CONTROLS.md`](CONTROLS.md).

---

## 9. Reproducing the baseline specifically

```powershell
conda activate carlaAir
python baseline\open_loop_agent.py
```

The agent writes `runs/agent-log.jsonl` itself — one JSON object per planning
call with the instruction, the model's raw output, the validated plan and
`plan_seconds`. No patching step, and nothing to remember to turn on: a run that
is not logged cannot be reported.

The mission set, the run protocol and what to record per run are in
[`BASELINE_MISSIONS.md`](BASELINE_MISSIONS.md).
