"""Run the guardrail benchmark for one model, or build the comparison table.

    python scripts/run_guardrail_benchmark.py --backend llama
    python scripts/run_guardrail_benchmark.py --backend mistral
    python scripts/run_guardrail_benchmark.py --backend gemini --model gemini-3.5-flash --pause 4
    python scripts/run_guardrail_benchmark.py --backend gemini --model gemini-3.5-flash --resume
    python scripts/run_guardrail_benchmark.py --table          # all results -> table

Each run writes results/benchmark/<model>.json: the three paper metrics (TRA,
GBR, MVL), the counters behind them, the model-only view, and every prompt with
the model's raw reply and what the guardian did with each step. `--table` then
writes results/benchmark/table.tex and table.csv from every result in the
directory, and refuses to mix results produced from different prompt suites.

No simulator is needed: approved steps are flown on the deterministic mock.
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agentic_uav.experiments import guardrail_benchmark as gb

OUT = os.path.join(gb.ROOT, "results", "benchmark")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", help="llama | mistral | gemini | ollama | scripted")
    ap.add_argument("--model", default=None, help="exact model name / tag")
    ap.add_argument("--repeat", type=int, default=1,
                    help="run the whole suite this many times")
    ap.add_argument("--cpu", action="store_true",
                    help="Ollama: keep the model off the GPU")
    ap.add_argument("--prompts", default=gb.DEFAULT_PROMPTS)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--table", action="store_true",
                    help="build the comparison table from existing results")
    ap.add_argument("--retries", type=int, default=6,
                    help="Gemini: retries per prompt on 503/429, with backoff")
    ap.add_argument("--pause", type=float, default=0.0,
                    help="seconds between prompts (Gemini's free tier rate-limits)")
    ap.add_argument("--resume", action="store_true",
                    help="keep the prompts an earlier run of this model answered "
                         "and only re-send the ones that failed")
    ap.add_argument("--list-gemini-models", action="store_true",
                    help="print the Gemini model names your key can use")
    args = ap.parse_args()

    if args.list_gemini_models:
        from dotenv import load_dotenv
        from google import genai
        load_dotenv()
        key = os.getenv("GEMINI_API_KEY")
        if not key:
            print("GEMINI_API_KEY is not set. Create .env in this folder with:\n"
                  '  Set-Content -Path .env -Value "GEMINI_API_KEY=your-key" '
                  "-Encoding ascii")
            return 2
        client = genai.Client(api_key=key)
        for m in client.models.list():
            print(m.name)
        return 0

    if args.table:
        rows = gb.load_results(args.out)
        if not rows:
            print(f"no results in {args.out}")
            return 1
        path = gb.write_table(rows, args.out)
        print(open(path, encoding="utf-8").read())
        print(f"wrote {path} and table.csv")
        return 0

    if not args.backend:
        ap.error("--backend is required unless --table is given")

    model = gb.make_model(args.backend, args.model, cpu_only=args.cpu,
                          retries=args.retries)
    print(f"\n=== Guardrail benchmark: {model.identity().get('model')} ===\n")
    if hasattr(model, "on_retry"):
        def on_retry(attempt, total, delay, err):
            e = str(err)
            code = "503 busy" if "503" in e else (
                ("429 per-minute limit" if "PerMinute" in e else "429 rate-limited")
                if "429" in e else "server error")
            print(f"        {code} - waiting {delay:.0f}s, then retrying "
                  f"(attempt {attempt + 1} of {total})", flush=True)
        model.on_retry = on_retry

    def progress(rep, r):
        tag = {"model_rejected": "REFUSED by model",
               "blocked": "BLOCKED by guardian",
               "modified": "made safe by guardian",
               "executed": "executed",
               "unparseable": "UNPARSEABLE reply",
               "backend_error": "BACKEND ERROR"}[r.outcome]
        if r.outcome in ("backend_error", "unparseable"):
            mark = "!! "              # no answer is never a right answer
        else:
            right = (r.expected == "invalid") == (r.outcome in ("model_rejected", "blocked"))
            mark = "ok " if right else "-- "
        if r.reused:
            print(f"  {mark}{r.prompt_id} [{r.expected:7s}] {tag:22s} (kept from earlier run)",
                  flush=True)
            return
        print(f"  {mark}{r.prompt_id} [{r.expected:7s}] {tag:22s} {r.text[:52]}",
              flush=True)
        if r.backend_error:
            print(f"        {r.backend_error[:100]}", flush=True)
        elif r.attempts > 1:
            print(f"        (answered after {r.attempts} attempts - server was busy)",
                  flush=True)

    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", str(model.identity().get("model")))
    path = os.path.join(args.out, f"{slug}.json")
    earlier = None
    if args.resume:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                earlier = json.load(f)
            left = sum(1 for d in earlier["prompts"] if d["outcome"] == "backend_error")
            print(f"Resuming {path}: {left} prompt(s) to re-send\n")
        else:
            print(f"Nothing to resume at {path} - running the full suite\n")
    try:
        result = gb.run_benchmark(model, args.prompts, repeat=args.repeat,
                                  progress=progress, pause_s=args.pause,
                                  resume_from=earlier)
    except gb.BenchmarkError as e:
        print(f"\nStopped: the backend refused the first prompt and will refuse "
              f"the rest the same way.\n  {str(e)[:300]}")
        if "404" in str(e) or "NOT_FOUND" in str(e):
            print("\nThat model name is not available to your key. List the ones "
                  "that are:\n  python scripts/run_guardrail_benchmark.py "
                  "--list-gemini-models")
        return 1
    os.makedirs(args.out, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1)

    print("\nBENCHMARK RESULTS")
    print(json.dumps({**result["metrics"], "Raw Counters": result["counters"]},
                     indent=4))
    for w in result["warnings"]:
        print(f"WARNING: {w}")
    print(f"\nsaved {path}")
    left = result["counters"]["backend_errors"]
    if result.get("stopped") == "daily quota used up":
        print(f"\nSTOPPED: this key's daily quota for {slug} is used up. "
              f"{left} prompt(s) still to run.\nThe answered prompts are saved. "
              f"When it resets (usually midnight Pacific time) run the same command with --resume.")
    elif result.get("stopped") == "interrupted":
        print(f"\nInterrupted - answered prompts saved. Re-run with --resume to "
              f"finish the other {left}.")
    elif left:
        print(f"\n{left} prompt(s) failed at the backend. Re-run with --resume to "
              f"re-send only those; this result is not used in --table until then.")
    return 1 if left else 0


if __name__ == "__main__":
    sys.exit(main())
