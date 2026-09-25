#!/usr/bin/env python3
"""Audit the repository. Run before every commit.

    python tools/audit_repo.py         # exit 0 clean, exit 1 with problems

WHAT IT IS FOR
--------------
A research repository fails slowly. Nothing crashes; a link rots, a document
keeps describing a file that was deleted, a generated page drifts from the
thing that generates it, and none of it is visible to someone reading a diff.
By the time it matters, the repository is the record of an experiment and the
record is wrong.

Each check below exists because that failure actually happened here, not
because it seemed like good practice.

THE CHECKS
----------
    1. dead links          -- every relative Markdown link resolves
    2. missing references  -- prose naming a script or document that is gone
    3. compilation         -- every tracked .py compiles
    4. purged material     -- removed third-party names have not crept back
    5. generated drift     -- regenerating the docs changes nothing  <-- the important one
    6. machine paths       -- reported as a note, not a failure
    7. secrets             -- api keys, tokens, passwords
    8. tracked junk        -- __pycache__, .bak, .pyc

Check 5 is the one that earns its keep: it caught documentation that still told
readers to run third-party code weeks after that code was purged.

EXIT CODE
---------
0 clean, 1 if anything in `problems` fired. Notes never fail the run -- they
are observations a human should weigh, not defects.

ADDING A CHECK
--------------
Append to `problems` for something that must be fixed, `notes` for something
worth seeing. Keep every check cheap: a check that takes a minute gets skipped,
and a skipped check is worse than no check because it implies coverage that is
not there.

EXEMPTIONS
----------
Two files are deliberately exempt from the purged-material check, because they
must name what they remove: this file's own table, and the doc generator's
substitution map. phases/ is exempt from checks 2 and 4 entirely -- recording
what was removed is that directory's whole purpose.
"""

import io
import os
import py_compile
import re
import subprocess
import sys

# Resolve the repository from this file's location rather than the working
# directory, so the audit can be run from anywhere.
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO)

problems: list[str] = []   # must be fixed; these set the exit code
notes: list[str] = []      # worth seeing; never fail the run


def tracked() -> list[str]:
    """Every file git tracks.

    Deliberately not a filesystem walk: untracked scratch files, build output
    and anything ignored are not part of the repository, and auditing them
    would produce noise nobody can act on.
    """
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
    # Relative links only: (?!https?:|#) skips external URLs, which would need
    # network access to verify, and same-page anchors.
    for target in re.findall(r"\]\((?!https?:|#)([^)]+)\)", text):
        # Links are relative to the file containing them, and may carry a
        # #fragment that is not part of the path.
        resolved = os.path.normpath(os.path.join(base, target.split("#")[0]))
        if not os.path.exists(resolved):
            problems.append(f"dead link: {path} -> {target}")

# ------------------------------------------- 2. references to missing files
# Catches prose that names a file which no longer exists -- the common decay
# after a rename or deletion, and invisible to the link check because backticks
# are not links.
#
# Anchored to the repository's own top-level directories so that `carla.Client`
# or a path in an unrelated example does not trigger it. Backticks are required:
# an unquoted path in a sentence is usually illustrative rather than a claim
# that the file exists.
CANDIDATE = re.compile(r"`((?:baseline|docs|tools|phases|runs|patches)[/\\][\w./\\-]+)`")
# phases/ is a historical record: it is supposed to name things that were
# removed, and rewriting it to keep an audit quiet would defeat its purpose.
HISTORICAL = "phases/"
for path in markdown + python:
    if path.startswith(HISTORICAL):
        continue
    text = io.open(path, encoding="utf-8").read()
    for ref in set(CANDIDATE.findall(text)):
        normalised = ref.replace("\\", "/")   # docs quote Windows-style paths
        if normalised.endswith("/"):
            continue                          # a directory reference, not a file
        if normalised.startswith("runs/"):
            # Run output is produced at runtime and git-ignored, so it exists on
            # a machine that has run something and not in a fresh clone. Docs
            # legitimately name it. Found by cloning and auditing the clone --
            # the check passed on the development machine and failed for the
            # exact reader the Phase 1 exit criterion is about.
            continue
        if not os.path.exists(normalised) and not any(
            # Placeholders in templates and instructions, where NN stands for a
            # number the reader fills in.
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
    if path in ("tools/build_carlaair_docs.py", "tools/audit_repo.py"):
        # The generator's substitution map and this file's own forbidden-string
        # table must name what they rewrite and search for.
        continue
    text = io.open(path, encoding="utf-8").read()
    for needle, what in FORBIDDEN.items():
        if needle in text:
            problems.append(f"mentions {what}: {path} -> {needle}")
    if "niranjanpillai" in text and not path.endswith(ALLOWED_CITATION):
        problems.append(f"names the upstream author outside the citation: {path}")

# --------------------------------------------- 5. generated docs are in sync
#
# The check that earns its keep. Snapshot the generated files, regenerate them,
# and compare: any difference means the committed docs no longer match what the
# generator produces, so either the manual changed or someone hand-edited a
# generated file.
#
# Note this REWRITES the files rather than working on copies. That is
# intentional -- if they were stale, the run leaves them correct and the diff
# ready to commit, instead of merely complaining about them.
#
# README.md and 00-architecture.md are hand-written and live in the same
# directory, so they are excluded by name.
before = {p: io.open(p, encoding="utf-8").read() for p in markdown
          if p.startswith("docs/carlaair/") and not p.endswith(("README.md", "00-architecture.md"))}
subprocess.run([sys.executable, "tools/build_carlaair_docs.py"],
               capture_output=True, text=True)
for path, old in before.items():
    if io.open(path, encoding="utf-8").read() != old:
        problems.append(f"generated doc is stale, regenerate: {path}")

# ------------------------------------------------ 6. machine-specific paths
#
# A NOTE, not a problem, because some of these are correct: the environment
# record is supposed to say exactly where things sat on the machine that
# produced the measurements. The rest are a wall for anyone else, and the
# Phase 1 exit criterion is explicitly about someone else reproducing this.
# Judging which is which needs a human, so the audit reports and moves on.
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
#
# Deliberately crude: an assignment of something named like a credential to a
# string of real length. It will not catch a key pasted with no label, and it
# is not a substitute for never putting one in a file. It exists because the
# Gemini path in this project's history read an API key from the environment,
# and that is the kind of thing that ends up hardcoded "just for a test".
SECRET = re.compile(r"(api[_-]?key|secret|token|password)\s*[:=]\s*[\"'][^\"']{8,}", re.I)
for path in markdown + python:
    for line in io.open(path, encoding="utf-8"):
        # The GitHub noreply address contains "token"-adjacent shapes in docs
        # about commit identity; it is public by design.
        if SECRET.search(line) and "noreply" not in line:
            problems.append(f"possible secret: {path}: {line.strip()[:60]}")

# ------------------------------------------------- 8. junk that should not be tracked
# Build artefacts and editor backups committed by accident. Cheap to check, and
# they are noise in every diff until someone notices.
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
