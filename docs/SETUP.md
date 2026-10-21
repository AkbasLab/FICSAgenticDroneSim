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

**The 4 GB VRAM figure is load-bearing, not incidental.** The simulator needs
most of it, so the study's model cannot run on this laptop at all. It runs on
a GPU server and is reached over an SSH tunnel (§7). It is also why the
factorial experiments are planned against a mock adapter rather than live
AirSim.

The laptop runs the simulator, the agent and the runner. A GPU server with
about 48 GB of free VRAM serves the model: for this study, one H100 80 GB on
ERAU's Vega cluster.

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

Extract to a path without spaces, then record where you put it. The rest of
this documentation refers to that location as **`%CARLAAIR_ROOT%`** rather than
naming one machine's drive letter:

```powershell
setx CARLAAIR_ROOT "C:\path\to\CarlaAir-v0.1.7-Windows11-x86_64"
```

`setx` affects only new sessions, so open a fresh terminal before continuing.
Check it took:

```powershell
cd $env:CARLAAIR_ROOT; Get-Location
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

From the repository root:

```powershell
$env:CONDA_DEFAULT_CHANNELS = "https://conda.anaconda.org/conda-forge"; conda env create -f environment.yml
```

```powershell
conda activate carlaAir
```

Python is **3.10.21**, built entirely from conda-forge, deliberately avoiding
the Anaconda commercial Terms of Service gate.

> **Why the first line sets a variable.** A fresh Miniconda's own `.condarc`
> adds the `defaults` channel to every command, and `conda env create` has no
> `--override-channels`. So even a conda-forge-only `environment.yml` stops at
> `CondaToSNonInteractiveError` for `repo.anaconda.com`. Setting
> `CONDA_DEFAULT_CHANNELS` for this window points `defaults` at conda-forge,
> so nothing needs accepting and your conda configuration is not changed. It
> lasts until you close the window. Verified from a GitHub clone on
> 2026-10-20: the environment built this way, plus the CARLA wheel below, has
> exactly the package set of the measured one.

### CARLA: install the wheel from the archive, not from PyPI

Neither `environment.yml` nor `requirements.txt` lists `carla`, on purpose.
Install the wheel that ships inside the CarlaAir archive, into the activated
environment:

```powershell
pip install $env:CARLAAIR_ROOT\PythonAPI\carla\dist\carla-0.9.16-cp310-cp310-win_amd64.whl
```

Wheel SHA-256: `f255c0fa2c89cdbd7b194546a45c03be45009033e4fece8c7021d13d9727fc33`

PyPI also has a `carla 0.9.16` wheel for this Python and platform, but it is a
**different build** (SHA-256 `5e7d46f1…865ca6`). The shipped one is what every
result was measured with. A plain `pip install carla==0.9.16` gets the PyPI
build silently, which is what `environment.yml` used to do. Check which one you
have:

```powershell
python -c "import importlib.metadata as m; print(m.distribution('carla').read_text('direct_url.json'))"
```

The shipped wheel prints a `file:///` URL into your CarlaAir folder with the
`f255c0fa…` hash. A PyPI install prints `None`.

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

## 7. The language model

**The study's model is `llama3.3:70b`**, 4-bit (42 GB), served by **Ollama
0.40.6** from one NVIDIA H100 80 GB. It does not run on the laptop: the laptop
has 4 GB of VRAM and the simulator needs most of it. So the model runs on a GPU
server and the laptop reaches it over an SSH tunnel. The simulator and the
agent stay on the laptop.

```
laptop                                      GPU server
  simulator  :2000 :41451                     ollama serve  0.0.0.0:11434
  agent ──► 127.0.0.1:11435 ══ SSH tunnel ══► <node>:11434
```

The protocol in `configs/missions/baseline_v1.toml` names the model and the
inference options. The runner refuses to start unless the endpoint is actually
serving `llama3.3:70b`, and it records the server's Ollama version on every
row.

### 7a. On ERAU's Vega cluster

This is how every valid run so far was served. The full procedure, with every
command verified and the traps explained, is the
[Vega HPC manual](vega/vega-carlaair-manual.pdf) (source and notes in
[`vega/`](vega/)). The short version:

**Once:** install Ollama 0.40.6 into `/scratch/$USER/ollama` from the release
tarball (no root needed, as it bundles its own CUDA), write an `env.sh` that
puts it on `PATH` and sets `OLLAMA_MODELS`, and pull `llama3.3:70b` from the
login node. Compute nodes have no internet.

**Every session**, on Vega:

```bash
ssh gpu01 nvidia-smi --query-gpu=index,memory.used,utilization.gpu --format=csv
ssh gpu02 nvidia-smi --query-gpu=index,memory.used,utilization.gpu --format=csv
```

```bash
qsub -I -q gpuq -l nodes=gpu01:ppn=48:gpus=1,mem=64gb,walltime=04:00:00
```

Name the node that has an idle card (near-zero memory **and** 0%). Then, inside
the job, first see whether the scheduler named a card for you:

```bash
echo "CUDA_VISIBLE_DEVICES=[$CUDA_VISIBLE_DEVICES]  PBS_GPUFILE=[$PBS_GPUFILE]"
nvidia-smi --query-gpu=index,memory.used,utilization.gpu --format=csv
```

```bash
source /scratch/$USER/ollama/env.sh
export CUDA_VISIBLE_DEVICES=N     # ONLY if the echo above showed it empty
OLLAMA_HOST=0.0.0.0:11434 OLLAMA_CONTEXT_LENGTH=98304 nohup ollama serve > /scratch/$USER/ollama/serve-gpu.log 2>&1 &
```

**If `CUDA_VISIBLE_DEVICES` is already set, keep it** — that is the card the
scheduler allocated to the job; skip the `export`. If it is empty, `N` is the
idle card's index, and without it the model can land on another user's GPU.
Earlier jobs had both variables empty; job 71111 on 2026-10-20 had
`CUDA_VISIBLE_DEVICES=1` and a `PBS_GPUFILE` set. Check every time.
`nvidia-smi` always lists all four cards whatever the variable says, so it
shows which are busy, not which is yours.

**On the laptop**, in a window you leave open. The node must be the one the job
is on:

```powershell
ssh -N -o ServerAliveInterval=30 -L 11435:gpu01:11434 <user>@vega.erau.edu
```

Check it from a second window. It must print a version:

```powershell
curl.exe http://127.0.0.1:11435/api/version
```

> **Every new job needs its own `ollama serve`.** The server dies with the job.
> A tunnel left over from an earlier job still listens on 11435, but `curl`
> gets `Connection was reset` until the server is started again.

### 7b. Any other GPU server

Nothing above is Vega-specific except the scheduler. Any machine with about
48 GB of free VRAM, running Ollama 0.40.6 bound to `0.0.0.0:11434` with
`llama3.3:70b` pulled, works the same way. Tunnel to it and pass
`--ollama-host http://127.0.0.1:11435`. Record the server and card in your
results. Temperature 0 is reproducible per server instance, but not always
across instances.

### 7c. Laptop-only smoke test (not study data)

To check the stack without a GPU server, run Ollama locally on the CPU with the
small model the project started on:

```powershell
ollama pull llama3.2:3b
```

```powershell
python scripts\run_missions.py --plan-only --model llama3.2:3b --option num_gpu=0 --option num_ctx=4096
```

`num_gpu=0` keeps the model on the CPU, leaving the GPU to the simulator.
`num_ctx=4096` keeps its cache to about 0.5 GB of RAM, where the protocol's
98,304 would reserve about 11 GB. The longest prompt is about 840 tokens, so
neither limit can be reached (`RUN_LEDGER.md` §4b). This exercises everything
except the model the study measures. **Results from
it are not baseline results.** Manifest and weight digests for `llama3.2:3b`
and `llama3.1:8b` are in `BASELINE_ENVIRONMENT.md` §7.

The cloud model `gemini-flash-latest` is **not used in the baseline**: it needs
an API key, sends data off-machine, and is a moving tag, which disqualifies it
from a frozen baseline.

---

## 8. Verify the whole stack

Start the simulator. For a quick check, a light launch is fine:

```powershell
cd $env:CARLAAIR_ROOT; .\CarlaAir.ps1 Town10HD --no-traffic --quality Low
```

That is **not** the protocol, which runs at the launcher defaults (Epic,
traffic on). Use the §9 launch for anything you intend to compare with the
baseline.

Then, in a second window with the environment active, run the self-test that
ships with CarlaAir. It lives in the CarlaAir folder, not in this repository:

```powershell
conda activate carlaAir; cd $env:CARLAAIR_ROOT; .\env_setup\TestEnv.ps1
```

It checks imports, a live CARLA connection on 2000 and a live AirSim connection
on 41451, and reports a PASS / FAIL / WARN tally.

For a first flight and the day-to-day commands, continue to
[`CONTROLS.md`](CONTROLS.md).

---

## 9. Reproducing the baseline specifically

You need the model endpoint from §7 answering on 11435, and the simulator
started **fresh**, under the protocol's conditions (Epic, 1080p, traffic on,
which are the launcher defaults):

```powershell
cd $env:CARLAAIR_ROOT; .\CarlaAir.ps1 Town10HD
```

Then, from the repository root, fly the ten missions **in increasing drone
count**. M09 and M10 spawn their extra drones as they need them:

```powershell
conda activate carlaAir
```

```powershell
python scripts\run_missions.py --missions M01,M02,M03,M04,M05,M06,M07,M08 --block repro --ollama-host http://127.0.0.1:11435
```

```powershell
python scripts\run_missions.py --missions M09 --block repro --ollama-host http://127.0.0.1:11435
```

```powershell
python scripts\run_missions.py --missions M10 --block repro --ollama-host http://127.0.0.1:11435
```

> **Restart the simulator before flying fewer drones again.** Drones spawned
> by M09 and M10 stay in the scene, parked on the other missions' flight paths.
> The runner checks for this before the first takeoff and refuses.

Each invocation writes its runs, a summary table and a snapshot of the code
that flew them to `phases/phase-01-baseline-freeze/results/`. Compare yours
against the citable block, `v6-polled`. The mission set, the protocol and what
each run records are in [`BASELINE_MISSIONS.md`](BASELINE_MISSIONS.md). Which
blocks are valid data, and why, is in
[`phases/RUN_LEDGER.md`](../phases/RUN_LEDGER.md).

To try the agent interactively instead, type your own instruction and fly it:

```powershell
python baseline\open_loop_agent.py --model llama3.3:70b --ollama-host http://127.0.0.1:11435
```

Without those two flags it plans with `llama3.2:3b` on a local Ollama, which
is the §7c smoke test, not the study's model. Every planning call, whatever
made it, is logged to `runs/agent-log.jsonl`.
