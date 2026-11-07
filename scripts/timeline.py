#!/usr/bin/env python3
"""One run's timeline as a page, or every run's in a batch with an index (Phase 17, AUV-16 17.2).

    python scripts/timeline.py runs/experiments/<batch>/<run_id>     # writes <run_id>/timeline.html
    python scripts/timeline.py runs/experiments/<batch>              # every run, and <batch>/timelines.html

Per drone: task, role, skills, communication outages, model decisions, guardian interventions, marks; for the
team: messages over time, partitions, reallocations, mission progress. From the run's directory alone. The batch's
index lists every run -- its configuration and outcome -- each linked to its timeline.
"""

from __future__ import annotations

import argparse
import html
import io
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from agentic_uav.experiments.timeline import render, timeline  # noqa: E402

INDEX = "timelines.html"


def index_page(batch_dir: str, models: list[dict]) -> str:
    rows = []
    for m in models:
        c, o = m["config"], m["outcome"]
        done = f"{o['completion_s']:.1f}" if o["completion_s"] is not None else "—"
        rows.append(f"<tr><td><a href=\"{html.escape(m['run_id'])}/timeline.html\">{html.escape(m['run_id'])}</a></td>"
                    f"<td>{html.escape(c['architecture'])}</td><td>{c['team_size']}</td>"
                    f"<td>{html.escape(c['network'])}</td><td>{html.escape(c['failure'])}</td><td>{c['seed']}</td>"
                    f"<td>{html.escape(c['planner'])}</td><td class=\"{'ok' if o['met'] else 'no'}\">"
                    f"{'met' if o['met'] else 'not met'}</td><td>{done}</td><td>{100 * o['coverage']:.1f} %</td></tr>")
    name = os.path.basename(os.path.normpath(batch_dir))
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Timelines {html.escape(name)}</title>
<style>
:root {{ color-scheme: light dark; --fg: #1d1d1f; --bg: #fff; --line: #e4e4e4; --ok: #3b8f5a; --no: #c0504d; }}
@media (prefers-color-scheme: dark) {{ :root {{ --fg: #e8e8e8; --bg: #161616; --line: #2f2f2f; }} }}
body {{ background: var(--bg); color: var(--fg); font: 14px system-ui, sans-serif; margin: 16px; }}
table {{ border-collapse: collapse; }} td, th {{ padding: 4px 10px; border-bottom: 1px solid var(--line); text-align: left; }}
a {{ color: inherit; }} .ok {{ color: var(--ok); }} .no {{ color: var(--no); font-weight: 600; }}
.wrap {{ overflow-x: auto; }}
</style></head><body>
<h1 style="font-size:18px">{html.escape(name)} — {len(models)} runs</h1>
<p>Each run's timeline: per drone its task, role, skills, outages, model decisions and guardian interventions; for the
team its messages, partitions, reallocations and progress.</p>
<div class="wrap"><table><tr><th>Run</th><th>Arch</th><th>Drones</th><th>Network</th><th>Failure</th><th>Seed</th>
<th>Planner</th><th>Outcome</th><th>Completion s</th><th>Coverage</th></tr>
{"".join(rows)}
</table></div></body></html>
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("path", help="a run directory, or a batch directory")
    args = parser.parse_args(argv)
    single = os.path.isfile(os.path.join(args.path, "manifest.json"))
    runs = [args.path] if single else sorted(
        os.path.join(args.path, d) for d in os.listdir(args.path)
        if os.path.isfile(os.path.join(args.path, d, "events.jsonl.gz")))
    models = []
    for r in runs:
        m = timeline(r)
        with io.open(os.path.join(r, "timeline.html"), "w", encoding="utf-8", newline="\n") as h:
            h.write(render(m))
        models.append(m)
    if not single and models:
        out = os.path.join(args.path, INDEX)
        with io.open(out, "w", encoding="utf-8", newline="\n") as h:
            h.write(index_page(args.path, models))
        print(f"{len(models)} timelines; index: {out}")
    elif models:
        print(os.path.join(runs[0], "timeline.html"))
    return 0 if models else 1


if __name__ == "__main__":
    sys.exit(main())
