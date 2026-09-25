#!/usr/bin/env python3
"""Audit the repository before a commit.

Checks the things that rot quietly: dead links, references to files that no
longer exist, Python that does not compile, generated docs that have drifted
from their generator, machine-specific paths, and anything that looks like a
secret.
"""

import io
import os
import py_compile
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO)

problems: list[str] = []
notes: list[str] = []


def tracked() -> list[str]:
    out = subprocess.run(["git", "-c", "safe.directory=*", "ls-files"],
                         capture_output=True, text=True)
    return [p for p in out.stdout.splitlines() if p]


files = tracked()
markdown = [f for f in files if f.endswith(".md")]
python = [f for f in files if f.endswith(".py")]

# ---------------------------------------------------------------- 1. links
for path in markdown:
    base = os.path.dirname(path)
    text = io.open(path, encoding="utf-8").read()
    for target in re.findall(r"\]\((?!https?:|#)([^)]+)\)", text):
        resolved = os.path.normpath(os.path.join(base, target.split("#")[0]))
        if not os.path.exists(resolved):
            problems.append(f"dead link: {path} -> {target}")

# ------------------------------------------- 2. references to missing files
# Anything that looks like a repo path mentioned in prose or code fences.
CANDIDATE = re.compile(r"`((?:baseline|docs|tools|phases|runs|patches)[/\\][\w./\\-]+)`")
# phases/ is a historical record: it is supposed to name things that were
# removed, and rewriting it to keep an audit quiet would defeat its purpose.
HISTORICAL = "phases/"
for path in markdown + python:
    if path.startswith(HISTORICAL):
        continue
    text = io.open(path, encoding="utf-8").read()
    for ref in set(CANDIDATE.findall(text)):
        normalised = ref.replace("\\", "/")
        if normalised.endswith("/"):
            continue
        if not os.path.exists(normalised) and not any(
            normalised.startswith(p) for p in ("phases/phase-NN", "docs/carlaair/NN")
        ):
            problems.append(f"references a missing path: {path} -> {ref}")

# ------------------------------------------------------- 3. python compiles
import tempfile

for path in python:
    # Compile to a scratch file: os.devnull is not a regular file on Windows.
    with tempfile.NamedTemporaryFile(suffix=".pyc", delete=False) as handle:
        cfile = handle.name
    try:
        py_compile.compile(path, cfile=cfile, doraise=True)
    except py_compile.PyCompileError as exc:
        problems.append(f"does not compile: {path}: {exc}")
    finally:
        os.unlink(cfile)

# ------------------------------------------- 4. purged material has not crept back
FORBIDDEN = {
    "apply_logging": "the removed logging patcher",
    "llama_airsim_agent": "the removed third-party agent",
    "mistral_airsim_agent": "the removed third-party agent",
    "gemini_airsim_agent": "the removed third-party agent",
    "PROVENANCE.md": "the removed provenance file",
    "baseline.patch": "the removed patch",
}
ALLOWED_CITATION = ("BASELINE_ENVIRONMENT.md", "phases/phase-01-baseline-freeze/README.md")
for path in markdown + python:
    if path.startswith(HISTORICAL):
        continue                      # the record may name what was removed
    if path == "tools/build_carlaair_docs.py":
        continue                      # its substitution map must name what it rewrites
    text = io.open(path, encoding="utf-8").read()
    for needle, what in FORBIDDEN.items():
        if needle in text:
            problems.append(f"mentions {what}: {path} -> {needle}")
    if "niranjanpillai" in text and not path.endswith(ALLOWED_CITATION):
        problems.append(f"names the upstream author outside the citation: {path}")

# --------------------------------------------- 5. generated docs are in sync
before = {p: io.open(p, encoding="utf-8").read() for p in markdown
          if p.startswith("docs/carlaair/") and not p.endswith(("README.md", "00-architecture.md"))}
subprocess.run([sys.executable, "tools/build_carlaair_docs.py"],
               capture_output=True, text=True)
for path, old in before.items():
    if io.open(path, encoding="utf-8").read() != old:
        problems.append(f"generated doc is stale, regenerate: {path}")

# ------------------------------------------------ 6. machine-specific paths
machine = re.compile(r"[A-Z]:\\(?:Research|AllSetups|Users)\\")
counts = {}
for path in markdown + python:
    hits = len(machine.findall(io.open(path, encoding="utf-8").read()))
    if hits:
        counts[path] = hits
if counts:
    total = sum(counts.values())
    notes.append(f"machine-specific absolute paths: {total} across {len(counts)} files")
    for path, n in sorted(counts.items(), key=lambda kv: -kv[1])[:6]:
        notes.append(f"    {n:3d}  {path}")

# -------------------------------------------------------------- 7. secrets
SECRET = re.compile(r"(api[_-]?key|secret|token|password)\s*[:=]\s*[\"'][^\"']{8,}", re.I)
for path in markdown + python:
    for line in io.open(path, encoding="utf-8"):
        if SECRET.search(line) and "noreply" not in line:
            problems.append(f"possible secret: {path}: {line.strip()[:60]}")

# ------------------------------------------------- 8. junk that should not be tracked
for path in files:
    if any(part in path for part in ("__pycache__", ".prelog.bak", ".pyc", ".bak")):
        problems.append(f"junk tracked: {path}")

# ------------------------------------------------------------------ report
print(f"tracked files:   {len(files)}  ({len(markdown)} markdown, {len(python)} python)")
for note in notes:
    print("  " + note)
print()
if problems:
    print(f"PROBLEMS ({len(problems)}):")
    for problem in problems:
        print("  " + problem)
    sys.exit(1)
print("audit: clean")
