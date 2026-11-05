#!/usr/bin/env python3
"""Phase 12's model choice: recorded decisions put to each candidate model.

    python scripts/llm_bench.py collect                                  # echo flights, seeds 1-5: no GPU
    python scripts/llm_bench.py run --requests <collected.jsonl> --models llama3.3:70b,llama3.1:8b \\
        --ollama-host http://127.0.0.1:11435 [--limit 200]

`collect` flies the canonical mission with the echo model (seeds 1-5, no stop and Drone1 stopped at 60 s)
and records every decision a model would have been asked: the exact messages and the rule's answer.
`run` asks each model those messages, one at a time, through the endpoint (on Vega: the SSH tunnel), with
the options of configs/llm/default.toml, and reports per model: replies valid at once, usable after the one
correction, falling back, agreeing with the rule policy, latency, and the actions chosen. How it is measured
is in `experiments/llm_bench.py`. The model the exit flies is chosen from this.

Outputs, under phases/phase-12-llm-agent-policy/results/ by default:

    llm-bench-requests-<stamp>.jsonl     collect: a header, then one request per line
    llm-bench-<stamp>[-<block>].jsonl    run: a header (models, digests, options, summaries), one row per reply
    llm-bench-<stamp>[-<block>].md       run: the table
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from agentic_uav.coordination.keepout import parse_keepout  # noqa: E402
from agentic_uav.experiments.allocation import load_allocation  # noqa: E402
from agentic_uav.experiments.guardian_exit import load_guardian  # noqa: E402
from agentic_uav.experiments.llm import llm_path, load_llm, served_digest  # noqa: E402
from agentic_uav.experiments.llm_bench import collect, run, sample, summarize  # noqa: E402
from agentic_uav.experiments.provenance import provenance  # noqa: E402
from agentic_uav.experiments.recovery import load_recovery  # noqa: E402
from agentic_uav.experiments.runner import load_toml  # noqa: E402
from agentic_uav.experiments.scenarios import load_scenario  # noqa: E402

DEFAULT_OUT = os.path.join(REPO, "phases", "phase-12-llm-agent-policy", "results")
KEEPOUT = os.path.join(REPO, "configs", "keepout", "default.toml")


def seeds_arg(text: str) -> tuple[int, ...]:
    out: list[int] = []
    for part in text.split(","):
        if "-" in part:
            a, b = part.split("-", 1)
            out += range(int(a), int(b) + 1)
        else:
            out.append(int(part))
    return tuple(out)


def write_jsonl(path: str, rows: list[dict]) -> None:
    with io.open(path, "w", encoding="utf-8", newline="\n") as h:
        for row in rows:
            h.write(json.dumps(row, default=str) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--seeds", type=seeds_arg, default=(1, 2, 3, 4, 5))
    c.add_argument("--out", default=DEFAULT_OUT)
    r = sub.add_parser("run")
    r.add_argument("--requests", required=True)
    r.add_argument("--models", required=True, help="comma-separated, as the server names them")
    r.add_argument("--ollama-host", required=True)
    r.add_argument("--limit", type=int, default=None, help="evenly spaced sample of the requests")
    r.add_argument("--out", default=DEFAULT_OUT)
    r.add_argument("--block", metavar="LABEL")
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
    os.makedirs(args.out, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")

    if args.cmd == "collect":
        fly = {"guardian": load_guardian(), "keep_out": parse_keepout(load_toml(KEEPOUT), KEEPOUT)}
        requests = collect(load_scenario("search_relay_001"), args.seeds, load_allocation(), load_recovery(), fly)
        path = os.path.join(args.out, f"llm-bench-requests-{stamp}.jsonl")
        write_jsonl(path, [{"kind": "header", "t": stamp, "seeds": list(args.seeds), "requests": len(requests),
                            "code": provenance()}] + [{"kind": "request", **q} for q in requests])
        print(f"{len(requests)} decisions recorded from echo flights, seeds {list(args.seeds)}\nraw     : {path}")
        return 0

    from agentic_uav.planners.llm_ask import OllamaAsk
    with io.open(args.requests, encoding="utf-8") as h:
        lines = [json.loads(line) for line in h]
    requests = sample([q for q in lines if q["kind"] == "request"], args.limit)
    config = load_llm()
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    rows, header = [], {"kind": "header", "t": stamp, "endpoint": args.ollama_host, "requests_file": args.requests,
                        "decisions": len(requests), "options": config.options, "timeout_s": config.timeout_s,
                        "manifest": os.path.relpath(llm_path(), REPO), "models": {}, "code": provenance()}
    for model in models:
        digest = served_digest(args.ollama_host, model)
        if digest is None:
            print(f"{model}: not served at {args.ollama_host} -- skipped", flush=True)
            continue
        print(f"{model} ({digest[:12]}): {len(requests)} decisions ...", flush=True)
        ask = OllamaAsk(model, args.ollama_host, config.options, config.timeout_s)
        got = run(requests, ask, model)
        rows += got
        header["models"][model] = {"digest": digest, **summarize(got)}
        s = header["models"][model]
        print(f"  valid {s['valid_first']}, usable {s['usable_after_one_correction']}, fallback {s['fallback']}, "
              f"agreed {s['agreed']}, p50 {s['latency_p50_s']} s", flush=True)

    lines = [f"# LLM bench — {len(requests)} recorded decisions", "",
             f"Run {stamp} at {args.ollama_host}; options {config.options}; one correction (12.6).", "",
             "| Model | Digest | Valid at once | Usable after one correction | Fallback | Agreed with the rule "
             "| p50 s | p95 s | Actions chosen |", "|---|---|---|---|---|---|---|---|---|"]
    for model, s in header["models"].items():
        n = s["decisions"]
        lines.append(f"| {model} | `{s['digest'][:12]}` | {s['valid_first']}/{n} | {s['usable_after_one_correction']}/{n} "
                     f"| {s['fallback']}/{n} | {s['agreed']}/{n} | {s['latency_p50_s']} | {s['latency_p95_s']} "
                     f"| {', '.join(f'{k} {v}' for k, v in s['tools'].items())} |")
    lines += ["", "Agreement with the rule policy is a sanity measure, not a score. Offline the guardian is not "
                  "asked; every offered action has passed the tools' own checks.", ""]
    stem = f"llm-bench-{stamp}" + (f"-{args.block}" if args.block else "")
    write_jsonl(os.path.join(args.out, stem + ".jsonl"), [header] + rows)
    with io.open(os.path.join(args.out, stem + ".md"), "w", encoding="utf-8", newline="\n") as h:
        h.write("\n".join(lines))
    print("\n".join(lines))
    print(f"raw     : {os.path.join(args.out, stem + '.jsonl')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
