#!/usr/bin/env python3
"""Build docs/carlaair/ from the CarlaAir Command Reference manual.

    python tools/build_carlaair_docs.py

WHY THIS EXISTS
---------------
The reference manual is a 3,400-line LaTeX document that compiles to a PDF. A
PDF is not much use inside a repository: you cannot grep it, diff it, or link
to a section from a README. So the manual's content is converted to Markdown
and committed.

The obvious alternative -- copy the useful parts into Markdown by hand -- fails
the moment the manual changes, because the two copies drift silently and
nobody notices until someone follows stale instructions. Generating instead
means `tools/audit_repo.py` can re-run this and diff the result, which turns
drift into a failed check rather than a surprise.

HOW IT WORKS
------------
Each output file is one coherent topic assembled from one or more LINE RANGES
of the manual. Ranges rather than section names because the manual has no
machine-readable structure: `tex2md.py` converts whatever lines it is handed.

    DOCS[filename] = (title, lead paragraph, [(first_line, last_line), ...])

CHANGING IT
-----------
* The manual gained a section       -> add its range to the right entry
* You want a new topic file         -> add a DOCS entry; update docs/carlaair/README.md
* A section should not be published -> leave its range out (see 08 below)
* The manual moved                  -> update TEX

After any change, re-run this script and commit the regenerated files together
with the change. Never hand-edit a generated file: the next run overwrites it,
and the audit will flag the difference in the meantime.

RANGES ARE LINE NUMBERS, AND LINE NUMBERS MOVE
----------------------------------------------
Editing the manual shifts every range after the edit. There is no guard against
this beyond reading the output, so check the generated files after touching the
source document -- a silently truncated section looks like a short section.
"""

import io
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

# The manual lives outside the repository: it is a personal document that
# compiles to a PDF, not project source. Update this path if it moves.
TEX = r"D:/Research/CarlaAirDocs/CarlaAir-Command-Reference-v1.0.tex"
OUT = os.path.join(REPO, "docs", "carlaair")

# Use the interpreter running this script for the child conversions, so a conda
# environment does not silently hand work to a different Python.
PYTHON = sys.executable

# filename: (title, lead paragraph, [(first, last), ...])
#
# Note 08 below: its ranges deliberately SKIP the manual's "LLM agent layer"
# section, which documents a third-party agent this project does not use.
# Publishing it would contradict the clean-room decision recorded in
# docs/BASELINE_ENVIRONMENT.md section 9.
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
        "The example scripts that come with the build, and an explicit list of "
        "what this build does not do.\n\n"
        "The manual's *LLM agent layer* section is deliberately **not** included: "
        "it documents a third-party agent this project does not use. The agent "
        "layer for this study is [`../../baseline/`](../../baseline/).",
        [(2168, 2197), (2304, 2358)],
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

# The manual was written when the agent layer was a third-party script. This
# project replaced it, so examples that invoke it by name are retargeted at our
# own agent — the point of those examples is the surrounding technique, not
# which file is being run.
SUBSTITUTIONS = {
    "python llama_airsim_agent.py": "python baseline/open_loop_agent.py",
    "python -u llama_airsim_agent.py": "python -u baseline/open_loop_agent.py",
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

    # One conversion per range. tex2md.py runs as a subprocess rather than an
    # import so that a crash converting one range names the file it failed on
    # and leaves the others untouched, instead of aborting the whole build with
    # a traceback from somewhere in the middle.
    for first, last in ranges:
        result = subprocess.run(
            [PYTHON, os.path.join(HERE, "tex2md.py"), TEX, str(first), str(last)],
            capture_output=True,
            text=True,
            # Explicit UTF-8: the manual contains em dashes and typographic
            # quotes, and Windows would otherwise decode the child's output
            # as cp1252 and mangle them.
            encoding="utf-8",
        )
        if result.returncode != 0:
            # Fail loudly and stop. A half-converted document that still looks
            # plausible is worse than no document.
            sys.exit("convert failed for %s: %s" % (name, result.stderr[:300]))
        body.append(result.stdout.strip())

    # Ranges are separated by a blank line so two sections never run together
    # into one paragraph.
    text = "\n\n".join(body).rstrip() + "\n"

    # Retarget examples that name the old third-party agent. Applied after
    # conversion, so the rule is written in terms of the Markdown a reader will
    # see rather than the LaTeX that produced it.
    for old, new in SUBSTITUTIONS.items():
        text = text.replace(old, new)

    path = os.path.join(OUT, name)
    # newline="\n" keeps line endings LF on Windows. Without it Python writes
    # CRLF, every regenerated file differs from the committed one in every
    # line, and the audit's drift check becomes useless noise.
    with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(HEADER.format(title=title, lead=lead))
        handle.write(text)
    print("  %-34s %6d bytes" % (name, os.path.getsize(path)))
