"""Which code produced a run: the commit, whether the tree was dirty, digests.

Moved verbatim from `baseline/open_loop_agent.py` in Phase 2 step 5. Two paths
there were `__file__` -- the repository, and the agent file whose name and
digest every record carries. Here they are named explicitly, so a record
still states the same agent it always did: `open_loop_agent.py`, the baseline's
entry point, plus one digest over this whole package.
"""

from __future__ import annotations

import os
import sys
from typing import Any

from ..planners.endpoint import OLLAMA_ENDPOINT

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
AGENT_PATH = os.path.join(REPO_ROOT, "baseline", "open_loop_agent.py")


def file_digest(path: str) -> str | None:
    """SHA-256 of a file, short form. None if it cannot be read."""
    import hashlib

    try:
        with open(path, "rb") as handle:
            return hashlib.sha256(handle.read()).hexdigest()[:16]
    except OSError:
        return None


def provenance() -> dict[str, Any]:
    """Which code produced this run.

    Required by the plan (`AUV-14` §14.2: git SHA, versions, config) and by
    anyone reading a result months later who needs the exact agent that flew it.

    A commit SHA alone is not enough. Development happens with a dirty working
    tree, and most runs in this project were flown from uncommitted code -- so
    the digest of the agent file is recorded too, and `dirty` says whether the
    tree had uncommitted changes at the time. A run whose digest matches no
    commit can still be identified by the snapshot the runner archives beside
    the data.
    """
    import subprocess

    repo = REPO_ROOT
    commit, dirty = None, None
    try:
        commit = subprocess.run(
            ["git", "-c", "safe.directory=*", "rev-parse", "--short", "HEAD"],
            cwd=repo, capture_output=True, text=True, timeout=10,
        ).stdout.strip() or None
        status = subprocess.run(
            ["git", "-c", "safe.directory=*", "status", "--porcelain"],
            cwd=repo, capture_output=True, text=True, timeout=10,
        ).stdout
        dirty = bool(status.strip())
    except (OSError, subprocess.SubprocessError):
        pass

    return {
        "commit": commit,
        "dirty": dirty,
        "agent": os.path.basename(AGENT_PATH),
        "agent_sha256": file_digest(AGENT_PATH),
        # Since Phase 2 the flying code is in agentic_uav/, so the entry point's
        # digest alone no longer identifies what flew. One digest over the
        # whole package, file names included, does.
        "agentic_uav_sha256": package_digest(),
        "python": sys.version.split()[0],
        "ollama_endpoint": OLLAMA_ENDPOINT,
    }


def package_digest() -> str | None:
    """SHA-256 over every agentic_uav module, names and contents, short form."""
    import glob
    import hashlib

    root = os.path.join(REPO_ROOT, "agentic_uav")
    paths = sorted(glob.glob(os.path.join(root, "**", "*.py"), recursive=True))
    if not paths:
        return None
    digest = hashlib.sha256()
    for path in paths:
        digest.update(os.path.relpath(path, REPO_ROOT).replace(os.sep, "/").encode())
        digest.update(b"\0")
        with open(path, "rb") as handle:
            digest.update(handle.read())
        digest.update(b"\0")
    return digest.hexdigest()[:16]
