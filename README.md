# Agentic UAV — Decentralized Coordination Study

Research repository for the study described in
[`docs/RESEARCH_PLAN.md`](docs/RESEARCH_PLAN.md).

> A decentralized team of persistent UAV agents that uses local belief states,
> structured peer communication, dynamic task allocation and bounded replanning
> can maintain greater **mission continuity** under communication degradation
> and agent loss than centralized planning or independent non-coordinating
> agents.

The claim is about **resilience**, not speed. Under nominal communication a
centralized controller is expected to win, and the plan says so in advance.

**Status:** Phase 1 — freezing and documenting the open-loop baseline.
Detailed phase tracking lives in the vault note `AUV-22 — Phase Objectives
Checklist`.

---

## What the baseline is

Tag `v0.1-open-loop-baseline` marks the system this project sets out to
improve on. In it:

- each drone receives a **separate** natural-language instruction;
- the language model generates a **complete action list before takeoff**;
- plans are **validated** before any vehicle arms;
- drones execute **concurrently**, one thread each;
- **no replanning happens after launch.**

That last property is the one everything from Phase 5 onward exists to remove.
The baseline is kept runnable so later architectures have a constant to be
measured against.

---

## Reproducing the baseline

Everything below was recorded from the machine the baseline was measured on.
Exact versions, hashes and the full rationale are in
[`docs/BASELINE_ENVIRONMENT.md`](docs/BASELINE_ENVIRONMENT.md) — read it if any
step surprises you.

### 1. Prerequisites

| Requirement | Detail |
|---|---|
| OS | Windows 11 x64 |
| DirectX End-User Runtime (June 2010) | **Install first.** Unreal 4.26 links seven legacy DirectX DLLs that Windows 11 does not ship; without them the simulator will not start |
| CarlaAir v0.1.7 | CARLA 0.9.16 + AirSim 1.8.1 in one Unreal process. Verify the archive against the SHA-256 in the environment doc |
| Miniconda | Python **3.10.21** environment named `carlaAir`, created from conda-forge |
| Ollama 0.34.x | With `llama3.2:3b` pulled. Model digests are recorded in the environment doc |
| GPU | 4 GB VRAM is enough — models run on **CPU** (`num_gpu: 0`); see below |

### 2. Environment

```powershell
conda env create -f environment.yml
conda activate carlaAir
```

`requirements.txt` is a `pip freeze` of the measured environment and is **not
portable as generated**: its `carla` entry is a local file URL. Install that one
wheel from your own CarlaAir install instead:

```powershell
pip install <carlaair-root>\PythonAPI\carla\dist\carla-0.9.16-cp310-cp310-win_amd64.whl
```

Do not downgrade NumPy below 2 — the CARLA extension module and OpenCV here are
built against the NumPy 2 ABI.

### 3. AirSim settings

AirSim reads `settings.json` from the Windows **Documents known folder**. With
OneDrive Known Folder Move — the Windows 11 default — that is
`%USERPROFILE%\OneDrive\Documents\AirSim\settings.json`, *not*
`%USERPROFILE%\Documents\AirSim\`.

The CarlaAir launcher deploys to the wrong one of those two on a redirected
profile, so its deployment is inert and the file must be maintained by hand.
The expected contents and SHA-256 are in the environment doc. It is read only at
process start — changing it means restarting the simulator.

### 4. Start the simulator

```powershell
.\CarlaAir.ps1 Town10HD --no-traffic --quality Low
```

No traffic: it removes a confound and frees GPU. Wait for both ports to report
ready.

### 5. Fly a mission

```powershell
conda activate carlaAir
python baseline\llama_airsim_agent.py
```

Answer the drone-count prompt, then type an instruction in plain English —
`fly forward for 5 seconds then return home and land`. The model plans, the plan
is validated, the drones fly it.

> Answering more than 1 to the drone-count prompt **rewrites `settings.json`
> permanently** with that many drones, and the simulator boots with that count
> from then on. Restore it afterwards or the single-drone missions become
> invalid.

### 6. Turn on logging before recording anything

The baseline agent prints but does not log, so planning latency and raw model
output cannot be recovered from a run afterwards.

```powershell
python tools\apply_logging.py           # patch
python tools\apply_logging.py --check   # verify, change nothing
python tools\apply_logging.py --revert  # undo
```

This appends one JSON object per planning call to `runs/agent-log.jsonl`:
instruction, raw output, model id, drone, and `plan_seconds`.

---

## The baseline mission set

[`docs/BASELINE_MISSIONS.md`](docs/BASELINE_MISSIONS.md) defines ten fixed
natural-language missions (M01–M10), three runs each, and what to record per
run. The same ten are re-run against every later architecture, so improvements
are measured against a constant.

**Do not edit a mission's instruction text after results are recorded.** If a
mission is badly worded, add `M11` rather than changing `M05`.

---

## Layout

```
docs/       RESEARCH_PLAN.md · BASELINE_ENVIRONMENT.md · BASELINE_MISSIONS.md
baseline/   the frozen open-loop agents, plus PROVENANCE.md
tools/      apply_logging.py
patches/    baseline.patch — the delta against the upstream tag
runs/       run output; contents are not tracked
```

The module tree the project refactors into during Phase 2 is specified in the
vault note `AUV-03 — Repository Architecture`.

---

## Provenance and licensing

The code in `baseline/` is **not original to this repository**. It comes from
`niranjanpillai2009-altr/AirSimRepo` at commit `e2b297d`, which declares **no
licence** — meaning all rights reserved by default.
[`baseline/PROVENANCE.md`](baseline/PROVENANCE.md) records where each file came
from and the three changes that were applied on top of the upstream tag.

A licence grant or written permission is required before this repository is
published. See the vault note `AUV-21 — Ethics, Licensing and Publication
Compliance`.
