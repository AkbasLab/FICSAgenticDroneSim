#!/usr/bin/env python3
"""Write settings.json for N drones, and say whether a restart is needed.

    python tools/write_roster.py 2        # two drones
    python tools/write_roster.py          # report the current roster, change nothing

WHY THIS EXISTS
---------------
Changing the number of drones means rewriting settings.json and restarting the
simulator, because AirSim reads that file only at process start. The roster is
therefore changed by hand between mission blocks -- M01-M08 with one drone, M09
with two, M10 with four.

Doing that through a one-line `python -c` incantation is error-prone, and
getting it wrong fails in a way that reads like a broken simulator rather than
a wrong roster: the flight reports "vehicle not found", or worse, the simulator
exits during startup with no error at all.

This does the one thing, prints the result, and says plainly whether the
running simulator now needs restarting.

It deliberately does NOT restart anything. What is running, and when it stops,
stays a human decision.
"""

from __future__ import annotations

import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "baseline"))

import open_loop_agent as agent  # noqa: E402  (path set above)


def current(path: str) -> list[str]:
    try:
        with open(path, encoding="utf-8-sig") as handle:
            return list(json.load(handle).get("Vehicles", {}))
    except (OSError, ValueError):
        return []


def main() -> int:
    path = os.path.join(agent.documents_dir(), "AirSim", "settings.json")
    before = current(path)

    if len(sys.argv) < 2:
        print(f"settings.json : {path}")
        print(f"roster        : {before or '(none)'}")
        print("\nPass a number to change it, e.g. tools/write_roster.py 2")
        return 0

    try:
        count = int(sys.argv[1])
    except ValueError:
        sys.exit(f"not a number: {sys.argv[1]}")
    if count < 1:
        sys.exit("need at least one drone")

    # exact=True so this tool can shrink a fleet as well as grow it. The
    # flight path deliberately never shrinks -- it reuses a larger roster
    # rather than rewriting and demanding a restart.
    written, changed = agent.write_settings(count, exact=True)
    after = current(written)

    print(f"settings.json : {written}")
    print(f"roster        : {before or '(none)'}  ->  {after}")

    if not changed:
        print("\nUnchanged. The running simulator already matches; no restart needed.")
        return 0

    print("\nCHANGED. AirSim reads this file only at process start, so the running")
    print("simulator is still flying the old roster. Restart it before flying:")
    print("  cd D:\\Research\\CarlaAirSetup\\CarlaAir-v0.1.7-Windows11-x86_64")
    print("  .\\CarlaAir.ps1 --kill")
    print("  .\\CarlaAir.ps1 Town10HD")
    return 0


if __name__ == "__main__":
    sys.exit(main())
