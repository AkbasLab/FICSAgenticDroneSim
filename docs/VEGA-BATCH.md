# Running a batch on Vega (Phases 17–18)

A batch whose model is the pinned llama3.3:70b runs **on a GPU node itself**: the flights, the metrics and the model on
one machine. (Over a tunnel, a drop mid-flight makes the model time out and the rule policy take over — the run
completes, quietly polluted. On the node it cannot happen.) Every step is run by a person; this file is the procedure
as it stood at the end of Phase 18, with what each step guards against.

Names: `chikhala` is the Vega user; replace it with yours. `/scratch/$USER` is fast, large and **not backed up**.

## Vega's rules (support, 2026-11-09, and what we measured)

| | |
|---|---|
| **2 running jobs a user, across all queues** | A third waits, whatever its queue (`checkjob <job>` says "MAXNODE limit of 2") |
| **Several GPUs in one job are allowed** | `-l nodes=gpu01:ppn=16:gpus=2,…` counts as one of the two; other users run 2-GPU jobs (`showq -r`) |
| `gpuq` up to **24 h**; **`longq` up to 120 h**, GPUs included | A long GPU workload goes to `longq` as one job rather than split |
| **Non-interactive jobs preferred** | Submit, walk away, be emailed |
| `ppn=8` is plenty for one batch | Our 16-core jobs kept 2.6–3.9 cores busy (`showq -r`, `EFFIC`) |

## Once: the code and a Python on Vega

**On the laptop** (PowerShell, **in the repository** — from your home folder `scp` has nowhere to put things), a bundle
of the branch — a real clone, so each run's manifest names its commit:

```
cd "D:\Research\Adi-MLOpsGit\Drone Agentic AI"
git bundle create "$HOME\auv-SC.bundle" SC
scp "$HOME\auv-SC.bundle" chikhala@vega.erau.edu:/scratch/chikhala/
```

(`git bundle create` runs where the commits are — on the laptop; on Vega it fails with "Permission denied".)

**On the Vega login node** (it has internet; the GPU nodes do not). Vega's default `python3` is 3.6.8, too old; its
module system has 3.11.7, which the environment is built on:

```
module load python/3.11.7-gcc-13.2.0-cxghnql
python3 -m venv /scratch/$USER/auv-venv
/scratch/$USER/auv-venv/bin/python -m pip install --upgrade pip
cd /scratch/$USER && git clone auv-SC.bundle auv && cd auv && git checkout SC && git log --oneline -1
/scratch/$USER/auv-venv/bin/python -m pip install -r requirements-vega.txt
/scratch/$USER/auv-venv/bin/python -c "import numpy, ollama, agentic_uav; print('ready')"
echo "defscrollback 10000" >> ~/.screenrc          # screen windows keep 10,000 lines (see "Screen")
```

(A bundle of one branch has no default branch: the clone warns "remote HEAD refers to nonexistent ref" and checks
nothing out; `git checkout SC` does.) The venv points at the module's Python by its full path (`pyvenv.cfg`), so it
runs on a GPU node without the module, which the GPU nodes do not list. Run the scripts from `/scratch/$USER/auv`.

**A newer commit later:** a new bundle, then `cd /scratch/$USER/auv; git pull ../auv-SC.bundle SC; git log --oneline -1;
git status --short` — the commit you expect, and **nothing** from `git status`: a run from a dirty tree is excluded
(docs/EXCLUSIONS.md, X4). Never pull while a batch is flying from that copy.

## Each time — the default: a non-interactive job

`docs/vega/phase18_d.pbs` does every step below by itself and **stops before flying** if one fails: the commit and a
clean tree; Ollama's libraries read first; the server's `inference compute` line must say CUDA, never the CPU; a
warm-up request; the batch (or its resume); the variability check once every run is complete; the server log copied
into the batch directory; PBS mails at begin, end and abort. Edit its `EXPECT=` commit and its `#PBS` lines for the
campaign at hand.

```
scp docs/vega/phase18_d.pbs chikhala@vega.erau.edu:/scratch/chikhala/        # laptop: beside the repo copy, not in it
cd /scratch/chikhala && grep -c $'\r' phase18_d.pbs && bash -n phase18_d.pbs   # Vega: 0 Windows line endings; syntax ok
qsub -v BATCH=phase18_d_four_b,PORT=11436 phase18_d.pbs                       # a new batch
qsub -l nodes=1:ppn=16:gpus=1,mem=64gb,walltime=02:00:00 \
     -v BATCH=phase18_d_pair,PORT=11434,RESUME=/scratch/chikhala/auv-runs/<batch dir> phase18_d.pbs   # a resume
```

* `-v` passes the settings; `-l` on the command line replaces the script's resources (here a 2-hour resume on any
  GPU node). Give each concurrent batch **its own port** (11434, 11435, 11436, …).
* **The walltime must cover the whole batch and its check.** Measured per D run: 2 drones 3–4 min; 4 drones nominal
  7–8, moderate ~9, partitioned/severe ~15–18; two at a time halves the wall time. A run cut off by the walltime
  leaves requests in the server log that no record holds (see "When something goes wrong").
* **While it runs**, its printout (`p18-d.o<job>`) is copied to `/scratch/chikhala/` only **when the job ends**. To see
  progress meanwhile:
  ```
  F=$(ls -d /scratch/$USER/auv-runs/phase18-d-four-b-* | tail -1); echo "$(ls $F/*/manifest.json | wc -l) runs complete"
  grep -i "inference compute" /scratch/$USER/ollama/serve-d-four-b-<job>.log        # CUDA, never cpu
  grep '/api/chat' /scratch/$USER/ollama/serve-d-four-b-<job>.log | tail -1          # a recent 200, ~7 s
  ```
* **When it ends**, PBS's "Execution terminated" mail says **`Exit_status=0`** if every step ran; anything else means a
  check stopped it — its printout says which.

## Each time — interactive, when a person must watch

One **laptop terminal tab per job**, named after it, each with its **own named screen session** (`screen -S four-a`;
later `screen -r four-a`). Then, step by step:

1. **Idle GPUs** — `pbsnodes` counts cores, not GPUs:
   ```
   for n in gpu01 gpu02; do echo "== $n"; ssh $n nvidia-smi --query-gpu=index,pci.bus_id,memory.used,utilization.gpu --format=csv,noheader; done
   ```
   A GPU at 0 MiB, 0 % is idle. Who holds the others: `--query-compute-apps=gpu_bus_id,pid,used_memory` with
   `ps -o user= -p <pid>` on that node.
2. **The job**: `qsub -I -q gpuq -l nodes=gpu01:ppn=16:gpus=1,mem=64gb,walltime=08:00:00`, then `hostname` — a GPU
   node, not `vegaln1`. (`echo $STY` prints nothing inside a `qsub -I` job even under screen; the test is
   `Ctrl+A` then `w`: a window list flashes if screen took the keys.)
3. **The code, clean**: `cd /scratch/$USER/auv; git log --oneline -1; git status --short` — the expected commit,
   nothing from `status`. Then the four exports:
   ```
   export OLLAMA_HOME=/scratch/chikhala/ollama
   export OLLAMA_MODELS=$OLLAMA_HOME/models
   export PATH=$OLLAMA_HOME/bin:$PATH
   export LD_LIBRARY_PATH=$OLLAMA_HOME/lib/ollama:$LD_LIBRARY_PATH
   ```
4. **Ollama's libraries read once** (its GPU discovery gives up after 30 s; on a slow scratch it then falls back to the
   CPU while still answering `curl` normally):
   `time timeout 180 find /scratch/$USER/ollama/lib/ollama -type f -exec cat {} + > /dev/null; echo "exit $?"` —
   `exit 0` in under a minute; `exit 124` or a hang means scratch is slow: stop.
5. **The server, its own port and log**:
   `OLLAMA_HOST=127.0.0.1:11435 OLLAMA_CONTEXT_LENGTH=8192 OLLAMA_NUM_PARALLEL=1 nohup ollama serve > /scratch/$USER/ollama/serve-<batch>-<n>.log 2>&1 &`
6. **GPU or CPU** (after ~40 s): `grep -i -E "inference compute|timed out" <that log>` — `library=CUDA … H100`, no
   `timed out`. `library=cpu`: stop, nothing flies (X3).
7. **Warm-up** (a cold first decision once timed out at 60 s — Phase 17, run 0022):
   ```
   curl -s http://127.0.0.1:11435/api/generate -d '{"model":"llama3.3:70b","prompt":"ready","stream":false,"options":{"num_ctx":8192,"num_predict":1,"temperature":0,"seed":0}}' | head -c 120; echo
   OLLAMA_HOST=127.0.0.1:11435 ollama ps        # llama3.3:70b … 100% GPU … 8192
   ```
   Start the batch **within 4 minutes**: an idle model unloads after 5. `/api/generate` is not counted among the
   batch's `/api/chat` requests.
8. **The batch**: `/scratch/$USER/auv-venv/bin/python scripts/run_batch.py <batch> --jobs 2 --ollama-host http://127.0.0.1:11435 --out /scratch/$USER/auv-runs`
9. **An email when it ends** — a second window of the same session (`Ctrl+A`, `c`: a login-node shell, which has
   `mail`), with `B` set to the batch directory **by its real name** (check `echo $B; ls $B | head -3` first: a
   placeholder left in `B=` counts nothing for hours):
   ```
   for i in $(seq 960); do n=$(ls $B/*/manifest.json 2>/dev/null | wc -l); [ "$n" -ge 80 ] && break; sleep 30; done; echo "$n of 80 runs finished in $B" | mail -s "Vega: $n/80 runs done" YOUR_EMAIL
   ```
   Then `Ctrl+A`, `D` detaches. Closing the laptop tab after that changes nothing on Vega.
10. **After the batch, in the same job**: warm up again (the model may have unloaded), then
    `scripts/model_variability.py <batch dir> --ollama-host http://127.0.0.1:<port>`; copy the server log into the
    batch directory; then `exit`. **Follow-on work goes in the job that already holds the GPU**, before `exit`.

## Screen

| | |
|---|---|
| `screen -S <name>` / `screen -r <name>` / `screen -d -r <name>` | Start, reattach, take over a session still "Attached" elsewhere |
| `Ctrl+A` then `c` / `0`…`9` / `"` / `D` | New window / go to a window / a list of windows / detach |
| `Ctrl+A` then `[` | **Scroll back** (copy mode): arrows, `k`/`j`, `Ctrl+B`/`Ctrl+F`; `Esc` leaves. Nothing typed reaches the program |
| `Ctrl+A` then `:` `scrollback 10000` | More history for a window already open (`~/.screenrc`'s `defscrollback` for new ones) |
| `screen -S <session> -p 0 -X hardcopy -h ~/w0.txt` | Save a window's whole history to a file, from any other shell |

**Never press Ctrl+C in a batch's window.** Before any Ctrl+C on Vega: `hostname; echo "job: $PBS_JOBID"; echo $STY $WINDOW`.
On 2026-11-09 a Ctrl+C meant for a waiting `qsub` in one window stopped a batch in another.

## The queue

| | |
|---|---|
| `qstat -u $USER` | Your jobs: `Q` waiting, `R` running, `C` ended |
| `checkjob <job> \| grep -i -E "^state\|block\|maxnode\|reserved"` | Why a job waits, and its reservation — a **latest** start, planned from requested walltimes; a job moves up when another ends early. Right after a job ends its GPU is reported free only after the node's clean-up |
| `showq -u $USER`, `showq -r` | Your jobs; every running job on Vega (`qstat` hides other users') |
| `qstat -q`, `qstat -Qf gpuq` | Each queue's running and waiting jobs; the queue's limits |
| `qdel <job>` | Cancel a job from the login node — also one whose shell hangs |

## When something goes wrong

| Seen | Meaning | Do |
|---|---|---|
| `curl` hangs, then answers; `inference compute … library=cpu` | GPU discovery timed out on a slow scratch; the model is on the CPU | Stop the server (`kill %1`), read the libraries (step 4), start it again; never fly on the CPU |
| A command ignores Ctrl+C; `scp` stalls at 0 % on one file | Scratch: the node that wrote the file holds it and does not answer | Another window or SSH; `lfs df -h /scratch` (servers up?), `time wc -c <file>`; `qdel` the stuck job; reads recover in minutes |
| The batch's prompt is back before all runs finished | The batch's parent stopped (a Ctrl+C) | `ps -u $USER -o pid,etime,args \| grep run_batch` **on the node**: orphaned workers may still be flying; let them finish or `kill` them, then `run_batch.py <batch> --resume <batch dir>` |
| A batch was interrupted and resumed | Its server log holds requests of the cut-off runs that no record holds | Investigate, then declare them in `<batch dir>/interruptions.json` (interval, why, excess and failed requests); `scripts/factorial_exit.py` verifies it (docs/EXCLUSIONS.md v2) |
| `qsub` waits with idle GPUs on the node | The 2-job limit (`checkjob`) | Leave it queued; it starts when one of yours ends |

## Back on the laptop

```
cd "D:\Research\Adi-MLOpsGit\Drone Agentic AI"
scp -r chikhala@vega.erau.edu:/scratch/chikhala/auv-runs/<batch dir> runs/experiments/
scp chikhala@vega.erau.edu:/scratch/chikhala/p18-d.o<job> runs/experiments/<batch dir>/
```

Copy into the ignored `runs/experiments/`, never straight into `phases/`: an untracked file in the repository makes
every later run `dirty` (X4). At the close the batches are copied into the phase's `results/`, the server logs gzipped
(`gzip -9 -n`; `*.log` is git-ignored), and `scripts/factorial_exit.py` run on those copies.
