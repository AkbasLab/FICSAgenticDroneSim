#!/usr/bin/env python3
"""A live model's residual variability: re-ask a batch's first recorded decisions (Phase 17; docs/TESTING.md 16.4).

    python scripts/model_variability.py runs/experiments/<pilot batch> --ollama-host http://127.0.0.1:11434

The first --n (100) decisions the model made in the batch, each rebuilt exactly from its recorded context (its
digest checked), asked again of the same server, pinned model and options, one at a time. Reports the fraction that
name the same tool with the same parameters, and every reply that differs, as it is. The server must serve the
pinned digest, or nothing is asked. Output: <batch>/model-variability-<stamp>.json and .md.
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

from agentic_uav.experiments.llm import load_llm, preflight  # noqa: E402
from agentic_uav.experiments.variability import ask_again, recorded_decisions  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("batch_dir")
    parser.add_argument("--n", type=int, default=100)
    parser.add_argument("--llm", default="default", help="the configs/llm manifest the batch was flown with")
    parser.add_argument("--ollama-host", required=True)
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
    cfg = load_llm(args.llm)
    problems = preflight(cfg, args.ollama_host)
    if problems:
        print("refused: " + "; ".join(problems))
        return 2
    from agentic_uav.planners.llm_ask import OllamaAsk
    sample = recorded_decisions(args.batch_dir, args.n)
    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    result = ask_again(sample, OllamaAsk(cfg.model, args.ollama_host, cfg.options, cfg.timeout_s))
    record = {"t": started, "batch_dir": args.batch_dir, "llm": cfg.as_json(), "endpoint": args.ollama_host,
              "sampled": len(sample), **result}
    stem = os.path.join(args.batch_dir, f"model-variability-{time.strftime('%Y%m%d-%H%M%S')}")
    with io.open(stem + ".json", "w", encoding="utf-8", newline="\n") as h:
        json.dump(record, h, indent=1)
    a = result["agreement"]
    lines = [f"# Model variability — {cfg.model}", "", f"{started}: {result['asked']} of {len(sample)} recorded decisions "
             f"asked again ({result['errors']} errors); **{result['agreed']} agreed"
             + (f" ({100 * a:.1f} %)" if a is not None else "") + "**.", ""]
    lines += [f"* {r['run_id']} {r['drone']} at {r['at']}: first {r['first']}, again {r['again']}"
              for r in result["rows"] if not r["agreed"] and "error" not in r][:50]
    with io.open(stem + ".md", "w", encoding="utf-8", newline="\n") as h:
        h.write("\n".join(lines) + "\n")
    print("\n".join(lines[:12]))
    return 0 if not result["problems"] else 1


if __name__ == "__main__":
    sys.exit(main())
