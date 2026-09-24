#!/usr/bin/env python3
"""Build docs/carlaair/ from the CarlaAir Command Reference.

Each output file is one coherent topic, assembled from the manual's own section
ranges so the content stays faithful and re-generable. Re-run after the manual
changes; do not hand-edit the generated bodies.
"""

import io
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
TEX = r"D:/Research/CarlaAirDocs/CarlaAir-Command-Reference-v1.0.tex"
OUT = os.path.join(REPO, "docs", "carlaair")
PYTHON = sys.executable

# filename: (title, lead paragraph, [(first, last), ...])
DOCS = {
    "01-simulator-control.md": (
        "Simulator Control",
        "Starting the simulator, stopping it, and controlling time inside it. "
        "Synchronous mode and tick control matter for experiments: a run that "
        "advances on wall-clock time is not reproducible.",
        [(167, 436)],
    ),
    "02-maps-and-navigation.md": (
        "Maps and Navigation",
        "The six towns, switching between them, and the road graph underneath "
        "them — waypoints, lanes, junctions and route planning.",
        [(437, 604)],
    ),
    "03-world-and-environment.md": (
        "World and Environment",
        "Weather, time of day, street lighting, and querying the static scene — "
        "everything about the world that is not an actor.",
        [(605, 760), (1454, 1544)],
    ),
    "04-actors-and-traffic.md": (
        "Actors and Traffic",
        "Spawning and controlling vehicles and pedestrians, driving a car "
        "manually, and the traffic light system.",
        [(761, 1094)],
    ),
    "05-drone-flight.md": (
        "Drone Flight",
        "The AirSim side: arming, taking off, flying by high-level commands, and "
        "low-level control. Read the NED warning before writing any flight code.",
        [(1095, 1273)],
    ),
    "06-sensors-and-perception.md": (
        "Sensors and Perception",
        "Cameras and sensors on both the CARLA and AirSim sides, and what the "
        "simulator can tell you about visibility, detection and occupancy.",
        [(1274, 1453)],
    ),
    "07-recording-and-monitoring.md": (
        "Recording, Debugging and Monitoring",
        "Recording and replaying a run, drawing into the world for debugging, "
        "and watching logs while the simulator is running.",
        [(1545, 2167)],
    ),
    "08-scripts-and-limits.md": (
        "Shipped Scripts and Known Limits",
        "The example scripts that come with the build, the agent layer that sits "
        "on top, and an explicit list of what this build does not do.",
        [(2168, 2358)],
    ),
    "09-diagnostics-and-reference.md": (
        "Diagnostics and Reference",
        "Symptoms and their causes, plus the ports, paths and constants worth "
        "keeping to hand.",
        [(2359, 2418), (3337, 3400)],
    ),
    "10-api-index.md": (
        "API Index",
        "Every public method of the principal classes, as installed. The method "
        "lists were produced by introspecting the modules on the reference "
        "machine, so nothing present in the build is missing here.",
        [(2422, 3336)],
    ),
}

HEADER = """# {title}

{lead}

> Part of the CarlaAir reference set — see [`README.md`](README.md) for the
> index. Generated from *CarlaAir Command Reference v1.0*; edit that manual and
> regenerate rather than editing this file.

---

"""

os.makedirs(OUT, exist_ok=True)

for name, (title, lead, ranges) in DOCS.items():
    body = []
    for first, last in ranges:
        result = subprocess.run(
            [PYTHON, os.path.join(HERE, "tex2md.py"), TEX, str(first), str(last)],
            capture_output=True, text=True, encoding="utf-8",
        )
        if result.returncode != 0:
            sys.exit("convert failed for %s: %s" % (name, result.stderr[:300]))
        body.append(result.stdout.strip())

    path = os.path.join(OUT, name)
    with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(HEADER.format(title=title, lead=lead))
        handle.write("\n\n".join(body).rstrip() + "\n")
    print("  %-34s %6d bytes" % (name, os.path.getsize(path)))
