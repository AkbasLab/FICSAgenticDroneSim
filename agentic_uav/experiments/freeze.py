"""The freeze (AUV-16 17.4): what decides a flight and its scoring, fixed before the main experiment.

    problems = check(root)                     # [] when the tree is its latest frozen version
    add_version(root, "why it changed")        # a new dated version, after a change that had to be made

WHY. After the pilots, AUV-16 17.4: "stop changing prompts; stop changing task
rules; stop changing metrics; freeze network profiles; freeze scenario
families". Phase 18 flies the held-out seeds; nothing that decides how the
drones fly, how the model is asked, or how a run is scored may be tuned after
those results are seen -- and a change that must still be made (a defect) must
be visible and dated, never silent. The same idea as the pre-registration of
docs/METRICS.md and docs/CONDITIONS.md: git shows the order.

WHAT. `configs/frozen.toml` lists, for each frozen version, every file in the
freeze's scope with its SHA-256, a date and a note. The scope:

    agentic_uav/                 all the flying code: the policies and the model's prompt and tools, the task
                                 rules (allocation, recovery, keep-out), the guardian, the network and failure
                                 simulation, the runner and the metrics
    configs/                     scenarios, network profiles, failures, architectures, the model manifest, the
                                 rules' settings -- all but configs/experiments/ (the batches still to be written)
    docs/METRICS.md              the metric definitions
    docs/CONDITIONS.md           the calibration rule and the levels it chose
    docs/EXCLUSIONS.md           Phase 18's exclusion, replacement and completeness rules (from version 3)

`check` recomputes the digests and says what changed, was added or removed
since the latest version; tests/test_freeze.py runs it in every suite and in
CI. A change goes in only with a new version: `python scripts/freeze.py --note
"..."`, which records today's date, the note, and the new digests. Digests are
of the file with line endings as LF (the repository's .gitattributes), so a
checkout's line endings never count as a change.
"""

from __future__ import annotations

import datetime
import hashlib
import os
import re
from typing import Any

FROZEN = "configs/frozen.toml"
SCOPE = ("agentic_uav", "configs", "docs/METRICS.md", "docs/CONDITIONS.md", "docs/EXCLUSIONS.md")
EXCLUDED = ("configs/experiments", "configs/frozen.toml")
COMMAND = 'python scripts/freeze.py --note "what changed and why"'

HEADER = '''# The freeze (AUV-16 17.4): every file that decides how the drones fly, how the model is asked, and how a run is
# scored, with its SHA-256, fixed after the pilots and before the main experiment. Written by scripts/freeze.py,
# checked by tests/test_freeze.py on every run of the suite (and in CI): a frozen file that differs from the latest
# version fails the suite. A change that must be made goes in only with a new, dated version:
#
#     python scripts/freeze.py --note "what changed and why"
#
# Scope: agentic_uav/, configs/ (not configs/experiments/), docs/METRICS.md, docs/CONDITIONS.md, docs/EXCLUSIONS.md.
# Digests are of the file with LF line endings. See agentic_uav/experiments/freeze.py.
'''


def _rel(root: str, path: str) -> str:
    return os.path.relpath(path, root).replace(os.sep, "/")


def in_scope(root: str) -> list[str]:
    """Every file the freeze covers, relative to `root`, sorted."""
    out = []
    for entry in SCOPE:
        top = os.path.join(root, entry)
        if os.path.isfile(top):
            out.append(entry)
            continue
        for dirpath, dirnames, filenames in os.walk(top):
            dirnames[:] = sorted(d for d in dirnames if d != "__pycache__")
            for name in filenames:
                if name.endswith(".pyc"):
                    continue
                rel = _rel(root, os.path.join(dirpath, name))
                if not any(rel == e or rel.startswith(e + "/") for e in EXCLUDED):
                    out.append(rel)
    return sorted(out)


def digest(path: str) -> str:
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read().replace(b"\r\n", b"\n")).hexdigest()


def digests(root: str) -> dict[str, str]:
    return {rel: digest(os.path.join(root, rel)) for rel in in_scope(root)}


def load(root: str) -> list[dict[str, Any]]:
    """The frozen versions, oldest first; [] if there is no freeze yet."""
    from .runner import load_toml
    path = os.path.join(root, FROZEN)
    if not os.path.isfile(path):
        return []
    return list(load_toml(path).get("version", []))


def version_problems(versions: list[dict[str, Any]]) -> list[str]:
    """Each version numbered in turn from 1, dated (YYYY-MM-DD, never earlier than the one before), with a note."""
    problems = []
    if not versions:
        return [f"no frozen version in {FROZEN}"]
    last = None
    for i, v in enumerate(versions, 1):
        if v.get("number") != i:
            problems.append(f"version {i} is numbered {v.get('number')!r}")
        date = v.get("date")
        if not isinstance(date, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            problems.append(f"version {i} has no date (YYYY-MM-DD): {date!r}")
        else:
            try:
                datetime.date.fromisoformat(date)
            except ValueError:
                problems.append(f"version {i}'s date is not a date: {date!r}")
            if last is not None and date < last:
                problems.append(f"version {i} is dated {date}, before version {i - 1} ({last})")
            last = date
        if not isinstance(v.get("note"), str) or not v["note"].strip():
            problems.append(f"version {i} has no note saying what changed and why")
        if not isinstance(v.get("files"), dict) or not v["files"]:
            problems.append(f"version {i} lists no files")
    return problems


def check(root: str) -> list[str]:
    """What keeps the tree from being its latest frozen version: [] when it is."""
    versions = load(root)
    problems = version_problems(versions)
    if not versions or not isinstance(versions[-1].get("files"), dict):
        return problems
    n, frozen, now = versions[-1].get("number"), versions[-1]["files"], digests(root)
    for rel in sorted(set(frozen) | set(now)):
        if rel not in now:
            problems.append(f"{rel}: frozen in version {n}, now missing")
        elif rel not in frozen:
            problems.append(f"{rel}: new in the frozen scope since version {n}")
        elif frozen[rel] != now[rel]:
            problems.append(f"{rel}: changed since frozen version {n}")
    if len(problems) > len(version_problems(versions)):
        problems.append(f"a change to a frozen file needs a new dated version: {COMMAND}")
    return problems


def add_version(root: str, note: str, date: str | None = None) -> dict[str, Any]:
    """Record the tree as a new frozen version with today's date (or `date`) and `note`; written to configs/frozen.toml."""
    if not note or not note.strip():
        raise ValueError("a frozen version needs a note saying what changed and why")
    versions = load(root)
    bad = version_problems(versions) if versions else []
    if bad:
        raise ValueError("configs/frozen.toml is not valid as it stands: " + "; ".join(bad))
    now = digests(root)
    if versions and versions[-1]["files"] == now:
        raise ValueError(f"nothing in the frozen scope changed since version {versions[-1]['number']}")
    version = {"number": len(versions) + 1, "date": date or datetime.date.today().isoformat(), "note": note.strip(),
               "files": now}
    if versions and version["date"] < versions[-1]["date"]:
        raise ValueError(f"dated {version['date']}, before version {versions[-1]['number']} ({versions[-1]['date']})")
    write(root, versions + [version])
    return version


def _toml_string(s: str) -> str:
    if "\n" in s:
        if '"""' in s:
            raise ValueError('a note may not contain """')
        return '"""\n' + s.replace("\\", "\\\\") + '\n"""'
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def write(root: str, versions: list[dict[str, Any]]) -> None:
    lines = [HEADER.rstrip("\n"), ""]
    for v in versions:
        lines += ["[[version]]", f"number = {v['number']}", f"date = {_toml_string(v['date'])}",
                  f"note = {_toml_string(v['note'])}", "", "[version.files]"]
        lines += [f"{_toml_string(rel)} = {_toml_string(h)}" for rel, h in sorted(v["files"].items())]
        lines.append("")
    with open(os.path.join(root, FROZEN), "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines))
