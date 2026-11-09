"""Phase 18's exit: every cell of the factorial has its valid paired replications, by predeclared criteria only.

Kept OUTSIDE the agentic_uav package on purpose (2026-11-09): a run's manifest records the package digest, and X4
holds every run to it -- so a fix to this checker, inside the package, would set aside every run already flown. It
is frozen all the same: configs/frozen.toml lists it (scripts/factorial_checks.py).

    runs = load_runs([abc_dir, d_pair_dir, d_four_a_dir, d_four_b_dir, ...])
    result = run_checks(runs, design(root))          # {check: [problem, ...]}, the cells, the exclusions
    write_replacements(result, design, out_dir)      # batch files for the reserve seeds the cells still need

AUV-22, Phase 18's exit: "every final cell has sufficient valid replications, and exclusions rest on predeclared
technical criteria rather than unfavourable outcomes." docs/EXCLUSIONS.md (version 1, committed before any held-out
run) declares the criteria; this module applies them exactly and checks the rest of Phase 18:

    design               every run is a cell of the design and a held-out seed (test, or a reserve the
                         replacement rule calls for), flown once; no development seed
    frozen_code          the tree the check runs from passes configs/frozen.toml's check, so the package
                         digest the runs are held to (X4) is the frozen code's
    exclusions           X1-X5 of docs/EXCLUSIONS.md, run by run -- reported, never a failure by itself: an
                         excluded run is replaced, and the cell's completeness is what counts
    paired_complete      each cell: 20 seeds with a valid run of every architecture; a seed with an excluded
                         run set aside for all four and the next reserve flown by all four
    common_random_numbers  for a cell and a seed, every architecture: the same scenario, network and failure
                         files (the faults as planned), the same roster and targets, each fault that took hold
                         within 1 s of its plan; and every message lost or received as the
                         seeded network draws it -- one function of (sender, recipient, message number)
    decisions_saved      18.4: every D decision with its model input, its replies, its validation, the action
                         and any fallback; every drone's guardian log
    variability          each D batch's model-variability report, its agreement (below 95 % flagged)
    requests_accounted   each D batch: the requests in its records = the POST /api/chat lines its server logs
                         show while it ran

X3 (the model off the GPU) reads the server logs kept in each D batch's directory (serve*.log, serve*.log.gz): a run
is covered by the log whose time span holds it, and must have a CUDA `inference compute` line before it and no
`library=cpu` line while it ran.
"""

from __future__ import annotations

import gzip
import io
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

ARCHS = ("A", "B", "C", "D")
LEVELS = {2: ("nominal", "moderate"), 4: ("nominal", "moderate", "partitioned", "severe")}
SCENARIOS = {2: "search_pair_001", 4: "search_relay_001"}
FAILURES = ("none", "drone1-at-60s")
REQUIRED = 20
FLAG_AGREEMENT = 0.95
FAULT_LAG_S = 1.0                 # a planned fault takes hold at the next step of the flight's clock, within this
MODEL_ARCHS = ("D",)
CHECKS = ("design", "frozen_code", "exclusions", "paired_complete", "common_random_numbers", "decisions_saved",
          "variability", "requests_accounted")
DECISION_KEYS = ("context", "prompt_digest", "replies", "latency_s", "tool", "parameters", "rule", "agreed",
                 "problems", "decision")


@dataclass(frozen=True)
class Design:
    cells: tuple[tuple[int, str, str], ...]          # (team size, network, failure)
    test: tuple[int, ...]
    reserve: tuple[int, ...]
    archs: tuple[str, ...] = ARCHS
    required: int = REQUIRED
    llm: dict[str, Any] = field(default_factory=dict, compare=False)
    package_digest: str | None = None
    live_model: bool = True          # D asked a model server (X3, X5, variability, requests); False for the echo


def design(root: str) -> Design:
    """Phase 18's design: the cells of docs/EXCLUSIONS.md, the held-out seeds, the pinned model, the frozen code."""
    from agentic_uav.experiments.heldout import load_heldout
    from agentic_uav.experiments.provenance import package_digest
    from agentic_uav.experiments.runner import load_toml
    test, reserve = load_heldout(root)
    cells = tuple((size, net, fail) for size in sorted(LEVELS) for net in LEVELS[size] for fail in FAILURES)
    cfg = load_toml(os.path.join(root, "configs", "llm", "default.toml"))
    llm = {"model": cfg["model"]["name"], "digest": cfg["model"]["digest"], "options": dict(cfg["options"]),
           "timeout_s": float(cfg["call"]["timeout_s"])}
    return Design(cells, tuple(test), tuple(reserve), llm=llm, package_digest=package_digest())


# ------------------------------------------------------------------------ the runs

@dataclass
class Run:
    path: str
    batch: str
    manifest: dict[str, Any] | None
    arch: str | None = None
    cell: tuple[int, str, str] | None = None
    seed: int | None = None

    @property
    def run_id(self) -> str:
        return os.path.basename(self.path)

    def load(self, name: str) -> Any:
        p = os.path.join(self.path, name)
        if not os.path.isfile(p):
            return None
        if name.endswith(".jsonl.gz"):
            with gzip.open(p, "rt", encoding="utf-8") as h:
                return [json.loads(line) for line in h]
        opener = gzip.open if name.endswith(".gz") else io.open
        with opener(p, "rt", encoding="utf-8") as h:
            return json.load(h)


def load_runs(batch_dirs: Iterable[str]) -> list[Run]:
    runs = []
    for b in batch_dirs:
        for name in sorted(os.listdir(b)):
            p = os.path.join(b, name)
            if not os.path.isdir(p) or not name[:4].isdigit():
                continue
            mp = os.path.join(p, "manifest.json")
            m = None
            if os.path.isfile(mp):
                with io.open(mp, encoding="utf-8") as h:
                    m = json.load(h)
            r = Run(p, b, m)
            if m is not None:
                c = m["config"]
                r.arch, r.seed = c["architecture"], c["seed"]
                r.cell = (c["team_size"], c["network"], c["failure"])
            runs.append(r)
    return runs


# ------------------------------------------------------------------- server logs (X3)

_GIN = re.compile(r"\[GIN\] (\d{4})/(\d{2})/(\d{2}) - (\d{2}:\d{2}:\d{2}) \| (\d{3}) \|.*POST\s+\"/api/chat\"")
_TIME = re.compile(r"time=(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})")
_COMPUTE = re.compile(r'msg="inference compute".*\blibrary=(\S+)')


@dataclass
class ServerLog:
    name: str
    first: str | None = None
    last: str | None = None
    compute: list[tuple[str, str]] = field(default_factory=list)      # (when, library)
    chats: list[tuple[str, str]] = field(default_factory=list)        # (when, HTTP status)


def read_server_logs(batch_dir: str) -> list[ServerLog]:
    logs = []
    for name in sorted(os.listdir(batch_dir)):
        if not name.startswith("serve") or not (name.endswith(".log") or name.endswith(".log.gz")):
            continue
        if name.endswith(".log") and os.path.isfile(os.path.join(batch_dir, name + ".gz")):
            continue                                              # the same log, kept compressed
        opener = gzip.open if name.endswith(".gz") else io.open
        log = ServerLog(name)
        with opener(os.path.join(batch_dir, name), "rt", encoding="utf-8", errors="replace") as h:
            for line in h:
                when = None
                g = _GIN.search(line)
                if g:
                    when = f"{g.group(1)}-{g.group(2)}-{g.group(3)}T{g.group(4)}"
                    log.chats.append((when, g.group(5)))
                else:
                    t = _TIME.search(line)
                    if t:
                        when = t.group(1)
                        c = _COMPUTE.search(line)
                        if c:
                            log.compute.append((when, c.group(1).strip('"')))
                if when:
                    log.first = log.first or when
                    log.last = when
        logs.append(log)
    return logs


def x3(run: Run, logs: list[ServerLog]) -> str | None:
    """Why the run's model was not shown on the GPU, or None."""
    s, f = run.manifest["started"], run.manifest["finished"]
    cover = [g for g in logs if g.first and g.first <= s and f <= g.last]
    if not cover:
        return "no server log in its batch covers the run"
    for g in cover:
        before = [lib for when, lib in g.compute if when <= s]
        during = [lib for when, lib in g.compute if s <= when <= f]
        if before and before[-1].upper() == "CUDA" and all(lib.upper() == "CUDA" for lib in during):
            return None
    return "its server log shows no CUDA inference before it, or another library while it ran"


# ---------------------------------------------------------------------- exclusions

def exclusions(runs: list[Run], d: Design) -> dict[str, str]:
    """run path -> the X1-X5 reason it is set aside (docs/EXCLUSIONS.md); runs not listed are valid."""
    out: dict[str, str] = {}
    logs = {b: read_server_logs(b) for b in {r.batch for r in runs if r.arch in MODEL_ARCHS}}
    for r in runs:
        m = r.manifest
        if m is None or m.get("status") != "completed":
            out[r.path] = "X1 crashed" + ("" if m is None else f": {(m.get('error') or {}).get('type')}")
            continue
        code = m.get("code") or {}
        if code.get("dirty") is not False or code.get("agentic_uav_sha256") != d.package_digest:
            out[r.path] = "X4 not the frozen code"
            continue
        if r.arch in MODEL_ARCHS and d.live_model:
            llm = ((m.get("model") or {}).get("llm") or {})
            if any(llm.get(k) != d.llm.get(k) for k in ("model", "digest", "options", "timeout_s")):
                out[r.path] = "X5 not the pinned model"
                continue
            rec = r.load("records.json.gz") or {}
            if any(e.get("kind") == "fallback" and any(str(p).startswith("no reply:") for p in e.get("problems", []))
                   for log in (rec.get("llm") or {}).values() for e in log["log"]):
                out[r.path] = "X2 the model did not answer"
                continue
            why = x3(r, logs[r.batch])
            if why:
                out[r.path] = "X3 " + why
    return out


# ------------------------------------------------------------------------ the cells

def cells(runs: list[Run], d: Design, excluded: dict[str, str]) -> dict[tuple, dict[str, Any]]:
    """Each cell: its valid paired seeds, the seeds set aside (and why), the reserves it still needs flown."""
    by = {}
    for r in runs:
        if r.manifest is not None:
            by.setdefault((r.cell, r.seed), {})[r.arch] = r
    out = {}
    for cell in d.cells:
        valid, aside, needed, flagged = [], [], [], False
        order = list(d.test) + list(d.reserve)
        want = d.required
        for i, seed in enumerate(order):
            if i >= len(d.test) and len(valid) >= want:
                break
            if i >= len(d.test) and len(valid) + len(needed) >= want:
                break
            arms = by.get((cell, seed), {})
            missing = [a for a in d.archs if a not in arms]
            if missing:
                needed.append((seed, missing))
                continue
            why = {a: excluded[arms[a].path] for a in d.archs if arms[a].path in excluded}
            if why:
                aside.append((seed, why))
            else:
                valid.append(seed)
        if len(valid) < want and not needed:
            flagged = True                                          # the reserves are used up
        out[cell] = {"valid": valid, "aside": aside, "needed": needed, "flagged": flagged}
    return out


# ---------------------------------------------------------------- the checks

def check_design(runs: list[Run], d: Design, table: dict) -> list[str]:
    p, seen = [], {}
    allowed = set(d.test) | set(d.reserve)
    for r in runs:
        if r.manifest is None:
            continue
        if r.arch not in d.archs or r.cell not in d.cells:
            p.append(f"{r.run_id}: not a cell of the design ({r.arch}, {r.cell})")
        c = r.manifest["config"]
        if r.cell and c.get("scenario") != SCENARIOS.get(r.cell[0]):
            p.append(f"{r.run_id}: scenario {c.get('scenario')} for {r.cell[0]} drones")
        if r.seed not in allowed:
            p.append(f"{r.run_id}: seed {r.seed} is not a held-out seed")
        key = (r.arch, r.cell, r.seed)
        if key in seen:
            p.append(f"{r.run_id}: flown twice (also {seen[key]})")
        seen[key] = r.run_id
    for cell, info in table.items():
        used = set(d.test) | {s for s, _ in info["aside"]} | set(info["valid"]) | {s for s, _ in info["needed"]}
        extra = sorted({r.seed for r in runs if r.cell == cell and r.seed in set(d.reserve) and r.seed not in used})
        if extra:
            p.append(f"{cell}: reserve seeds flown that the replacement rule does not call for: {extra}")
    return p


def check_frozen(root: str | None) -> list[str]:
    if root is None:
        return []
    from agentic_uav.experiments.freeze import check as freeze_check
    return [f"the tree is not its frozen version: {x}" for x in freeze_check(root)]


def check_cells(table: dict, d: Design) -> list[str]:
    p = []
    for cell, info in table.items():
        if info["needed"]:
            p.append(f"{cell}: {len(info['valid'])} valid paired seeds; still to fly: "
                     + "; ".join(f"seed {s} ({', '.join(a)})" for s, a in info["needed"]))
    return p


def _fates(r: Run, events: list[dict], model) -> list[str]:
    bad = []
    for e in events:
        if e["type"] == "MESSAGE_RECEIVED" or (e["type"] == "MESSAGE_DROPPED" and e.get("why") == "lost"):
            sender, _, seq = e["message_id"].rpartition("#")
            lost, _ = model.draw(sender, e["drone"], int(seq))
            if lost != (e["type"] == "MESSAGE_DROPPED"):
                bad.append(f"{r.run_id}: {e['message_id']} to {e['drone']} "
                           f"{'lost' if e['type'] == 'MESSAGE_DROPPED' else 'received'}, the draw says otherwise")
                if len(bad) >= 3:
                    break
    return bad


def check_crn(runs: list[Run], d: Design) -> list[str]:
    from agentic_uav.experiments.conditions import load_network
    p = []
    groups: dict = {}
    for r in runs:
        if r.manifest is not None and r.manifest.get("status") == "completed":
            groups.setdefault((r.cell, r.seed), []).append(r)
    nets: dict = {}
    for (cell, seed), rs in sorted(groups.items(), key=lambda kv: (str(kv[0][0]), kv[0][1])):
        shared = {}
        for r in rs:
            m, rep = r.manifest, r.load("report.json") or {}
            ev = r.load("events.jsonl.gz") or []
            files = {k: (m.get("files") or {}).get(k, {}).get("sha256") for k in ("scenario", "network", "failure")}
            facts = (rep.get("report") or {}).get("facts") or {}
            start = next((e for e in ev if e["type"] == "MISSION_STARTED"), {})
            # The faults as PLANNED are the common random number, and the failure file's digest above pins them. A
            # planned stop can find nothing to stop -- in A, with severe links, Drone1 can be landed before 60 s --
            # so the faults that took hold may differ: each is held to within FAULT_LAG_S of its plan instead (it
            # takes hold at the next step of the architecture's own clock: A's controller 60.1 s for 60 s).
            injected = [e for e in ev if e["type"] == "FAULT_INJECTED"]
            for e in injected:
                if e.get("planned_s") is not None and not 0 <= e["t"] - e["planned_s"] <= FAULT_LAG_S:
                    p.append(f"{cell} seed {seed}: {r.arch}'s {e.get('fault')} planned at {e['planned_s']} s "
                             f"took hold at {e['t']} s")
            mine = {"files": files, "targets": facts.get("targets"), "seed": facts.get("random_seed"),
                    "roster": start.get("roster")}
            for k, v in mine.items():
                if k in shared and shared[k][1] != v:
                    p.append(f"{cell} seed {seed}: {k} differs between {shared[k][0]} and {r.arch}")
                shared.setdefault(k, (r.arch, v))
            key = (cell[1], seed)
            if key not in nets:
                nets[key] = load_network(cell[1]).seeded(seed)
            p += _fates(r, ev, nets[key])
    return p


def check_decisions(runs: list[Run]) -> list[str]:
    p = []
    for r in runs:
        if r.manifest is None or r.arch not in MODEL_ARCHS or r.manifest.get("status") != "completed":
            continue
        rec = r.load("records.json.gz") or {}
        ev = r.load("events.jsonl.gz") or []
        roster = next((e.get("roster") for e in ev if e["type"] == "MISSION_STARTED"), []) or []
        llm, guards = rec.get("llm") or {}, rec.get("guardians") or {}
        for drone in roster:
            if drone not in llm or not llm[drone].get("log"):
                p.append(f"{r.run_id}: no decision log for {drone}")
                continue
            if drone not in guards:
                p.append(f"{r.run_id}: no guardian log for {drone}")
            for e in llm[drone]["log"]:
                if e.get("kind") == "procedural":
                    continue
                gone = [k for k in DECISION_KEYS if k not in e]
                if gone:
                    p.append(f"{r.run_id}: {drone} at {e.get('at')}: {e.get('kind')} decision without {', '.join(gone)}")
                    break
                if e.get("kind") == "fallback" and not e.get("problems"):
                    p.append(f"{r.run_id}: {drone} at {e.get('at')}: a fallback without why")
                    break
    return p


def check_variability(runs: list[Run]) -> tuple[list[str], dict[str, float]]:
    p, agree = [], {}
    for b in sorted({r.batch for r in runs if r.arch in MODEL_ARCHS}):
        reps = sorted(n for n in os.listdir(b) if n.startswith("model-variability-") and n.endswith(".json"))
        if not reps:
            p.append(f"{os.path.basename(b)}: no model-variability report")
            continue
        with io.open(os.path.join(b, reps[-1]), encoding="utf-8") as h:
            rep = json.load(h)
        agree[os.path.basename(b)] = rep.get("agreement")
        if rep.get("errors"):
            p.append(f"{os.path.basename(b)}: the variability check had {rep['errors']} errors")
    return p, agree


def check_requests(runs: list[Run]) -> list[str]:
    p = []
    for b in sorted({r.batch for r in runs if r.arch in MODEL_ARCHS}):
        rs = [r for r in runs if r.batch == b and r.manifest is not None and r.arch in MODEL_ARCHS]
        if not rs:
            continue
        asked = 0
        for r in rs:
            for log in ((r.load("records.json.gz") or {}).get("llm") or {}).values():
                asked += sum(len(e.get("latency_s") or []) for e in log["log"] if e.get("prompt_digest"))
        lo, hi = min(r.manifest["started"] for r in rs), max(r.manifest["finished"] for r in rs)
        chats = [st for g in read_server_logs(b) for when, st in g.chats if lo <= when <= hi]
        if len(chats) != asked:
            p.append(f"{os.path.basename(b)}: {asked} requests in the records, {len(chats)} in the server logs")
        bad = [st for st in chats if st != "200"]
        if bad:
            p.append(f"{os.path.basename(b)}: {len(bad)} requests not answered (HTTP {sorted(set(bad))})")
    return p


def run_checks(runs: list[Run], d: Design, root: str | None = None) -> dict[str, Any]:
    excluded = exclusions(runs, d)
    table = cells(runs, d, excluded)
    var_p, agree = check_variability(runs) if d.live_model else ([], {})
    problems = {
        "design": check_design(runs, d, table),
        "frozen_code": check_frozen(root),
        "exclusions": [],
        "paired_complete": check_cells(table, d),
        "common_random_numbers": check_crn(runs, d),
        "decisions_saved": check_decisions(runs),
        "variability": var_p,
        "requests_accounted": check_requests(runs) if d.live_model else [],
    }
    flags = [f"{os.path.basename(b)}: model agreement {a:.1%}, under {FLAG_AGREEMENT:.0%}"
             for b, a in agree.items() if a is not None and a < FLAG_AGREEMENT]
    flags += [f"{cell}: the reserves are used up with {len(info['valid'])} valid paired seeds"
              for cell, info in table.items() if info["flagged"]]
    return {"problems": problems, "excluded": {os.path.relpath(k, os.path.dirname(os.path.dirname(k))): v
                                               for k, v in sorted(excluded.items())},
            "cells": {f"{c[0]}-{c[1]}-{c[2]}": {"valid": len(i["valid"]), "aside": [[s, w] for s, w in i["aside"]],
                                                 "needed": [[s, a] for s, a in i["needed"]], "flagged": i["flagged"]}
                      for c, i in table.items()},
            "agreement": agree, "flags": flags,
            "met": not any(problems.values()), "runs": len(runs)}


def write_replacements(result: dict[str, Any], d: Design, out_dir: str, stem: str) -> list[str]:
    """Batch files for the reserve runs the cells still need: <stem>_abc.toml (laptop) and <stem>_d.toml (Vega)."""
    blocks = {"abc": [], "d": []}
    for key, info in result["cells"].items():
        size, net, fail = key.split("-", 2)
        size = int(size)
        for seed, archs in info["needed"]:
            if int(seed) in set(d.test):
                continue                                     # a test seed not yet flown: its own batch, not a reserve
            for part, want in (("abc", [a for a in archs if a not in MODEL_ARCHS]),
                               ("d", [a for a in archs if a in MODEL_ARCHS])):
                if want:
                    blocks[part].append((size, net, fail, int(seed), want))
    written = []
    for part, rows in blocks.items():
        if not rows:
            continue
        text = (f"# Phase 18 replacements by docs/EXCLUSIONS.md: reserve seeds, in order, for cells with a seed set aside.\n"
                f"\n[batch]\nid = \"{stem.replace('_', '-')}-{part}\"\ndescription = \"reserve seeds by docs/EXCLUSIONS.md\"\n")
        for i, (size, net, fail, seed, archs) in enumerate(rows, 1):
            text += (f"\n[[experiment]]\nid = \"r{i}\"\narchitecture = {json.dumps(archs)}\n"
                     f"scenario = \"{SCENARIOS[size]}\"\nteam_size = {size}\nnetwork = \"{net}\"\nfailure = \"{fail}\"\n"
                     f"seed = {seed}\nplanner = \"{'llm:default' if part == 'd' else 'none'}\"\n")
        path = os.path.join(out_dir, f"{stem}_{part}.toml")
        with io.open(path, "w", encoding="utf-8", newline="\n") as h:
            h.write(text)
        written.append(path)
    return written


def report_md(result: dict[str, Any]) -> str:
    lines = [f"# Phase 18 exit — {'MET' if result['met'] else 'NOT MET'}", "",
             f"{result['runs']} runs read. Criteria: docs/EXCLUSIONS.md, version 1.", "", "| Check | Problems |", "|---|---|"]
    for k in CHECKS:
        n = len(result["problems"][k])
        lines.append(f"| {k} | {'none' if n == 0 else n} |")
    lines += ["", "## Cells", "", "| Cell | Valid paired seeds | Set aside | Still to fly |", "|---|---|---|---|"]
    for c, i in result["cells"].items():
        lines.append(f"| {c} | {i['valid']}{' (flagged)' if i['flagged'] else ''} | {len(i['aside'])} | {len(i['needed'])} |")
    if result["excluded"]:
        lines += ["", "## Excluded runs", ""] + [f"* `{k}`: {v}" for k, v in result["excluded"].items()]
    if result["agreement"]:
        lines += ["", "## Model variability", ""] + [f"* {b}: {a:.1%}" for b, a in result["agreement"].items() if a is not None]
    if result["flags"]:
        lines += ["", "## Flags", ""] + [f"* {f}" for f in result["flags"]]
    for k in CHECKS:
        if result["problems"][k]:
            lines += ["", f"## {k}", ""] + [f"* {x}" for x in result["problems"][k][:50]]
    return "\n".join(lines) + "\n"


def mini_design(cells_: Iterable[tuple[int, str, str]], test: Iterable[int], reserve: Iterable[int],
                required: int, package: str | None, llm: dict[str, Any], live_model: bool = True) -> Design:
    """A small design for tests and dry runs, with the same rules."""
    return Design(tuple(cells_), tuple(test), tuple(reserve), required=required, llm=llm, package_digest=package,
                  live_model=live_model)
