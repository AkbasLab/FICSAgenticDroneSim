# Running a batch on Vega (Phase 17)

A batch whose model is the pinned llama3.3:70b runs **on the GPU node itself**: the flights, the metrics and the
model on one machine, the batch inside `screen`, so a laptop asleep or a dropped connection cannot break a run.
(Over the tunnel, a drop mid-flight makes the model time out and the rule policy take over — the run completes,
quietly polluted. On the node it cannot happen.) Every step is run by a person, one at a time.

Names: `chikhala` is the Vega user; replace it with yours. `/scratch/$USER` is fast, large and **not backed up**.

## Once: the code and a Python on Vega

**On the laptop** (PowerShell, the repository), a bundle of the branch — a real clone, so each run's manifest names
its commit — copied to Vega:

```
git bundle create auv-SC.bundle SC
scp auv-SC.bundle chikhala@vega.erau.edu:/scratch/chikhala/
```

**On the Vega login node** (it has internet; the GPU nodes do not), inside `screen -S vega`:

```
cd /scratch/$USER && git clone auv-SC.bundle auv && cd auv && git log --oneline -1
python3 -m pip install --user uv
~/.local/bin/uv python install 3.10 --install-dir /scratch/$USER/python
~/.local/bin/uv venv /scratch/$USER/auv-venv --python 3.10
~/.local/bin/uv pip install --python /scratch/$USER/auv-venv/bin/python -r requirements-vega.txt
/scratch/$USER/auv-venv/bin/python -c "import numpy, ollama, agentic_uav; print('ready')"
```

(If `python3 -m pip` is missing on the login node, `uv` has a standalone installer; ask before using it.)

**A newer commit later:** a new bundle, then in `/scratch/$USER/auv`: `git pull ../auv-SC.bundle SC`.

## Each time: the job, the model, the batch

1. **Login node**: `screen -S vega` (or `screen -r vega`).
2. **The GPU job** (4 hours): `qsub -I -q gpuq -l nodes=gpu02:ppn=48:gpus=1,mem=64gb,walltime=04:00:00`
3. **On the node**, the four exports, as in the Vega manual:
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
6. **The model's variability** (docs/TESTING.md's protocol), same job, after the batch:
   ```
   /scratch/$USER/auv-venv/bin/python scripts/model_variability.py /scratch/$USER/auv-runs/<the batch directory> --ollama-host http://127.0.0.1:11434
   ```
7. **Back on the laptop**, the batch copied into the phase's results:
   ```
   scp -r chikhala@vega.erau.edu:/scratch/chikhala/auv-runs/<the batch directory> "phases/phase-17-pilot-experiments/results/"
   ```
