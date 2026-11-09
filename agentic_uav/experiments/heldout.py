"""The held-out seeds (AUV-16 17.4, 18.2): Phase 18's test seeds, drawn after the freeze and derived from it.

    test, reserve = draw(freeze_digest(versions[0]))      # 20 seeds, then 10 reserves in order
    test, reserve = load_heldout(root)                     # as committed in configs/seeds/heldout.toml

WHY. AUV-16 18.2: development scenarios for implementation and prompt
adjustment, validation scenarios for the pilots' calibration, HELD-OUT test
scenarios for the final results -- and "do not tune the LLM prompt after
examining held-out results". Every seed flown so far is a development seed:
1-20 (every exit since Phase 5, the calibration, the pilots) and 17 (the
scenario files' own). The held-out seeds must be none of those, fixed before
anything flies on them, and not chosen.

HOW, so that nobody chose them: they are DERIVED from freeze version 1
(configs/frozen.toml), committed before they were drawn. Its digest -- SHA-256
over its number, date, note and every frozen file's digest, as canonical JSON
-- seeds a counter: the k-th candidate is SHA-256("<digest>:<k>") read as an
integer, mapped into LOW..HIGH; a candidate already drawn or a development seed
is passed over. The first TEST are the test seeds; the next RESERVE, in their
order, replace a run only if it is excluded by a technical criterion declared
before Phase 18 is flown. Anyone can recompute them from the freeze; a
different set would need a different freeze. Plain hashing and integer
arithmetic: the same on every Python version (a seeded `random` need not be).
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

HELDOUT = "configs/seeds/heldout.toml"
LOW, HIGH = 1000, 999_999          # far from every development seed
TEST, RESERVE = 20, 10             # AUV-16 Phase 18: 20 seeds a cell; reserves for technical exclusions only
DEVELOPMENT = frozenset(range(1, 21)) | {17}


def freeze_digest(version: dict[str, Any]) -> str:
    """SHA-256 of a frozen version as canonical JSON: its number, date, note and files."""
    body = {k: version[k] for k in ("number", "date", "note", "files")}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
                          .encode("ascii")).hexdigest()


def draw(digest: str, test: int = TEST, reserve: int = RESERVE) -> tuple[list[int], list[int]]:
    """The test seeds and the reserves, in order, derived from `digest`."""
    free = (HIGH - LOW + 1) - len({s for s in DEVELOPMENT if LOW <= s <= HIGH})
    if free < test + reserve:
        raise ValueError(f"{LOW}..{HIGH} holds {free} seeds that are not development seeds; {test + reserve} needed")
    out: list[int] = []
    k = 0
    while len(out) < test + reserve:
        n = int(hashlib.sha256(f"{digest}:{k}".encode("ascii")).hexdigest(), 16)
        seed = LOW + n % (HIGH - LOW + 1)
        if seed not in out and seed not in DEVELOPMENT:
            out.append(seed)
        k += 1
    return out[:test], out[test:]


def load_heldout(root: str) -> tuple[list[int], list[int]]:
    from .runner import load_toml
    data = load_toml(os.path.join(root, HELDOUT))["heldout"]
    return list(data["test"]), list(data["reserve"])


def write_heldout(root: str, version: dict[str, Any]) -> tuple[list[int], list[int]]:
    """Draw from frozen `version` and write configs/seeds/heldout.toml."""
    digest = freeze_digest(version)
    test, reserve = draw(digest)
    text = f'''# The held-out seeds (AUV-16 17.4, 18.2): Phase 18's test seeds. Never flown before Phase 18, never tuned on.
# DERIVED, not chosen, from freeze version {version["number"]} ({version["date"]}) in configs/frozen.toml, committed before they were
# drawn: see agentic_uav/experiments/heldout.py. tests/test_heldout.py recomputes them from the freeze.
#
# test     the {TEST} seeds every Phase 18 cell flies
# reserve  in this order, each replaces a run ONLY if that run is excluded by a technical criterion declared
#          before Phase 18 is flown -- never because of its outcome
#
# Development seeds (1-20, and 17) are none of these; all lie in {LOW}..{HIGH}.

[heldout]
from_freeze_version = {version["number"]}
freeze_digest = "{digest}"
test = [{", ".join(map(str, test))}]
reserve = [{", ".join(map(str, reserve))}]
'''
    path = os.path.join(root, HELDOUT)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return test, reserve
