# Guardrail benchmark: TRA, GBR and MVL across models

Runs Llama, Mistral and Gemini through the same prompts, the same system prompt
and the same runtime-safety guardian, and produces the paper's table. No
simulator is needed; approved steps are flown on the deterministic mock.

## What it measures

| Metric | Definition (matching the OBA benchmark's counters) |
|---|---|
| **TRA** Task Rejection Accuracy | correctly rejected invalid prompts / invalid prompts. Rejected = the model refused, or the guardian blocked a step. |
| **GBR** Guardrail Breach Rate | executed steps that breach a boundary / executed steps |
| **MVL** Mean Verification Latency | mean time for one guardian verification, in ms |

Plus four columns describing the **model alone**, before the guardian:

| | |
|---|---|
| TRA model-only | invalid prompts the model refused by itself |
| Unguarded breach rate | proposed steps that would breach a boundary with no guardian |
| False rejection rate | valid prompts that were refused or blocked |
| TRA incl. clamping | TRA counting a clamped request ("climb to 500 m" flown at 60 m) as handled |

**Read the two levels separately.** The guardian does not depend on the model,
so GBR is expected to be about 0% for every model. That is the paper's claim, and
the benchmark could disprove it. The model-to-model differences appear in the
model-only columns. The false rejection rate matters because TRA on its own
rewards a model that refuses everything.

Breaches are judged by an independent checker, not by the guardian. The checker
is stricter: it checks the straight-line path to a waypoint as well as the
waypoint itself.

## Setup (once, Windows PowerShell)

```powershell
conda activate carlaAir
pip install ollama google-genai python-dotenv pyyaml

ollama pull llama3.1:8b
ollama pull mistral-nemo
```

Gemini key, written in ASCII (`echo >` writes UTF-16 and breaks it):

```powershell
Set-Content -Path .env -Value "GEMINI_API_KEY=your-key-here" -Encoding ascii
```

`.env` is gitignored. Never commit it or paste the key into chat.

**Pin the Gemini model.** `gemini-flash-latest` changes underneath you, so a
result recorded with it can't be reproduced. List the names your key can use and
pick a dated one:

```powershell
python scripts/run_guardrail_benchmark.py --list-gemini-models
```

## Run (about 22 prompts per model)

```powershell
python scripts/run_guardrail_benchmark.py --backend llama
python scripts/run_guardrail_benchmark.py --backend mistral
python scripts/run_guardrail_benchmark.py --backend gemini --model <pinned-name> --pause 4
python scripts/run_guardrail_benchmark.py --table
```

Each run prints a line per prompt, then a `BENCHMARK RESULTS` block in the same
format as the OBA benchmark. Results go to `results/benchmark/<model>.json`,
including every raw model reply, so any number in the table can be traced to the
replies that produced it. `--table` writes `results/benchmark/table.tex` (paste
it into Overleaf) and `table.csv`.

`--pause 4` keeps Gemini's free tier under its rate limit. `--repeat 3` runs the
whole suite three times if you want to see run-to-run variation; temperature is
0, but cloud models are not guaranteed to be deterministic.

## Things to tell Taner before the numbers go in the paper

1. **Same harness for all three rows.** If the existing Llama row came from a
   different script or prompt set, rerun Llama here too. Otherwise the table
   compares the harnesses as much as the models. The table refuses to combine
   results from different prompt suites for this reason.
2. **MVL here is a few hundredths of a millisecond**, versus 12.12 ms in the OBA
   video. That difference is about what gets timed. This times the guardian's
   decision alone; the OBA benchmark may include other work in its timing. Worth
   checking before the two appear in one table.
3. **Clamping vs rejection.** Decide whether a request the guardian *narrowed*
   into the envelope counts towards TRA. Both values are reported.
4. **The model is allowed to refuse.** The benchmark gives the model an explicit
   `reject` option and tells it the operating envelope, identically for every
   model. Without a way to refuse, model-level TRA is zero by construction.
