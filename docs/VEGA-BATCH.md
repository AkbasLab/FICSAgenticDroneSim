# Running a batch on Vega (Phase 17)

A batch whose model is the pinned llama3.3:70b runs **on the GPU node itself**: the flights, the metrics and the
model on one machine, the batch inside `screen`, so a laptop asleep or a dropped connection cannot break a run.
(Over the tunnel, a drop mid-flight makes the model time out and the rule policy take over — the run completes,
quietly polluted. On the node it cannot happen.) Every step is run by a person, one at a time.

Names: `chikhala` is the Vega user; replace it with yours. `/scratch/$USER` is fast, large and **not backed up**.

## Once: the code and a Python on Vega

**On the laptop** (PowerShell, the repository), a bundle of the branch — a real clone, so each run's manifest names
its commit — copied to Vega. `scp` runs on the machine that has the file:

```
git bundle create "$HOMEuv-SC.bundle" SC
scp "$HOMEuv-SC.bundle" chikhala@vega.erau.edu:/scratch/chikhala/
```

**On the Vega login node** (it has internet; the GPU nodes do not), inside `screen -S vega`. Vega's default
`python3` is 3.6.8, too old; its module system has 3.11.7, which the environment is built on:

```
module load python/3.11.7-gcc-13.2.0-cxghnql
python3 -m venv /scratch/$USER/auv-venv
/scratch/$USER/auv-venv/bin/python -m pip install --upgrade pip
cd /scratch/$USER && git clone auv-SC.bundle auv && cd auv && git checkout SC && git log --oneline -1
/scratch/$USER/auv-venv/bin/python -m pip install -r requirements-vega.txt
/scratch/$USER/auv-venv/bin/python -c "import numpy, ollama, agentic_uav; print('ready')"
```

(A bundle of one branch has no default branch: the clone warns "remote HEAD refers to nonexistent ref" and
checks nothing out, and `git checkout SC` does.)

The venv points at the module's Python by its full path (`pyvenv.cfg`), so it runs on a GPU node without the
module, which the GPU nodes do not list. Run the scripts from `/scratch/$USER/auv`. (Without a usable module, `uv python install 3.10` builds a standalone Python
instead — the route the laptop's WSL took in Phase 16.)

**A newer commit later:** a new bundle, then in `/scratch/$USER/auv`: `git pull ../auv-SC.bundle SC`.

## Each time: the job, the model, the batch

1. **Login node**: `screen -S vega` (or `screen -r vega`).
2. **The GPU job** (4 hours): `qsub -I -q gpuq -l nodes=gpu02:ppn=48:gpus=1,mem=64gb,walltime=04:00:00`
3. **On the node**, the four exports, as in the Vega manual (no `module load`: the GPU nodes list only a different
   build, `python/3.11.7-gcc-8.5.0-…`, and the venv runs without it — its Python, under `/apps/spack/…`, is reachable
   from the node):
   ```
   export OLLAMA_HOME=/scratch/chikhala/ollama
   export OLLAMA_MODELS=$OLLAMA_HOME/models
   export PATH=$OLLAMA_HOME/bin:$PATH
   export LD_LIBRARY_PATH=$OLLAMA_HOME/lib/ollama:$LD_LIBRARY_PATH
   ```
4. **The model server, on the node only** (no tunnel needed):
   ```
   OLLAMA_HOST=127.0.0.1:11434 OLLAMA_CONTEXT_LENGTH=8192 OLLAMA_NUM_PARALLEL=1 nohup ollama serve > /scratch/$USER/ollama/serve-gpu.log 2>&1 &
   curl -s http://127.0.0.1:11434/api/version
   ```
5. **The batch** (the server's digest is checked before the first run; nothing asks a question):
   ```
   cd /scratch/$USER/auv
   /scratch/$USER/auv-venv/bin/python scripts/run_batch.py phase17_pilot --jobs 2 --ollama-host http://127.0.0.1:11434 --out /scratch/$USER/auv-runs
   ```
   If the job ends before the batch does, a new job and the same command with `--resume <the batch directory>`
   flies only what is unfinished.
   **An email when it ends** (optional): in a second screen window (`Ctrl+A`, then `C` — a shell on the login node,
   which has `mail`; never `Ctrl+C`, which would stop the batch), with `B` set to the batch directory:
   ```
   for i in $(seq 130); do n=$(ls $B/*/manifest.json 2>/dev/null | wc -l); [ "$n" -ge 80 ] && break; sleep 120; done; echo "$n of 80 runs finished in $B" | mail -s "Vega pilot batch: $n/80 runs done" YOUR_EMAIL
   ```
   Every run writes its `manifest.json` last, so the count is the finished runs. Then `Ctrl+A`, `D` detaches both.
6. **The model's variability** (docs/TESTING.md's protocol), same job, after the batch:
   ```
   /scratch/$USER/auv-venv/bin/python scripts/model_variability.py /scratch/$USER/auv-runs/<the batch directory> --ollama-host http://127.0.0.1:11434
   ```
7. **Back on the laptop**, the batch copied into the phase's results:
   ```
   scp -r chikhala@vega.erau.edu:/scratch/chikhala/auv-runs/<the batch directory> "phases/phase-17-pilot-experiments/results/"
   ```
