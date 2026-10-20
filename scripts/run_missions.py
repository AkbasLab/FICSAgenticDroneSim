#!/usr/bin/env python3
"""Run a mission set against the baseline agent and score the plans.

The command line of the mission runner. Since Phase 2 step 5 the runner itself
is `agentic_uav/experiments/runner.py`; `--help` gives the usage, the outputs
and the scoring rule, unchanged.

    python scripts/run_missions.py --plan-only
    python scripts/run_missions.py --missions M01,M02,M03,M04,M05,M06,M07,M08 --block blockA

Kept at this path, under this name, because the flight procedure, the results
README and every code snapshot since Phase 1 refer to it. The runner's names
are re-exported, so `from run_missions import score` still works.
"""

from __future__ import annotations

import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from agentic_uav.experiments.runner import (  # noqa: E402,F401  (re-exported)
    DEFAULT_CONFIG,
    DEFAULT_OUT,
    connect_simulator,
    current_roster,
    describe,
    fly_one,
    load_toml,
    main,
    run_one,
    score,
    series_conflicts,
    snapshot_code,
    summarise,
)

if __name__ == "__main__":
    sys.exit(main())
