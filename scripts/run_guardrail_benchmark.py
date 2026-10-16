"""Run the guardrail benchmark for one model, or build the comparison table.

    python scripts/run_guardrail_benchmark.py --backend llama
    python scripts/run_guardrail_benchmark.py --backend mistral
    python scripts/run_guardrail_benchmark.py --backend gemini --model gemini-2.5-flash
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
    ap.add_argument("--pause", type=float, default=0.0,
                    help="seconds between prompts (Gemini's free tier rate-limits)")
    ap.add_argument("--list-gemini-models", action="store_true",
                    help="print the Gemini model names your key can use")
    args = ap.parse_args()

    if args.list_gemini_models:
        from dotenv import load_dotenv
        from google import genai
        load_dotenv()
        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
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

    model = gb.make_model(args.backend, args.model, cpu_only=args.cpu)
    print(f"\n=== Guardrail benchmark: {model.identity().get('model')} ===\n")

    def progress(rep, r):
        tag = {"model_rejected": "REFUSED by model",
               "blocked": "BLOCKED by guardian",
               "modified": "made safe by guardian",
               "executed": "executed",
               "unparseable": "UNPARSEABLE reply",
               "backend_error": "BACKEND ERROR"}[r.outcome]
        right = (r.expected == "invalid") == (r.outcome in ("model_rejected", "blocked"))
        mark = "ok " if right else "-- "
        print(f"  {mark}{r.prompt_id} [{r.expected:7s}] {tag:22s} {r.text[:52]}",
              flush=True)
        if r.backend_error:
            print(f"        {r.backend_error[:100]}", flush=True)

    result = gb.run_benchmark(model, args.prompts, repeat=args.repeat,
                              progress=progress, pause_s=args.pause)
    os.makedirs(args.out, exist_ok=True)
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", str(result["model"]["model"]))
    path = os.path.join(args.out, f"{slug}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1)

    print("\nBENCHMARK RESULTS")
    print(json.dumps({**result["metrics"], "Raw Counters": result["counters"]},
                     indent=4))
    for w in result["warnings"]:
        print(f"WARNING: {w}")
    print(f"\nsaved {path}")
    return 1 if result["counters"]["backend_errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
