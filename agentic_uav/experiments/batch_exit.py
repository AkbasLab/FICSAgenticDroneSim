"""Phase 14's exit: a batch command runs a list of configurations unattended, one complete directory per run.

    problems = run_checks(batch, out_dir)            # {check: [problem, ...]} on a finished batch directory
    compare_batches(first, second)                   # what differs between two runs of one batch

AUV-14's exit criterion: "a batch command executes a list of scenario
configurations without manual prompts and produces one complete result
directory per run." Checked on `configs/experiments/phase14_exit.toml`,
flown by `scripts/run_batch.py` as a child process with no input:

    unattended             the command ran to its end with nothing to read from, exit code 0
    one_directory_per_run  every run of the batch has its directory, and the index lists each once, in order
    manifests_complete     every manifest holds 14.2's fields: the configuration, each file read with its
                           digest, the commit, dirty flag and package digest, software versions, the model,
                           start and finish, the status, and the outcome (or the error)
    every_event_type       all 19 of 14.3's types happen, each in a real flight of the batch
    events_well_formed     in each run: in time order; one start, one completion, agreeing with the report;
                           every skill started has its end; every delivery belongs to a message sent
    as_configured          each run flew what its configuration says: the architecture, scenario, network,
                           failure, seed and planner in its start event and report; its stops, injection and
                           partitions as its profiles; a model consulted only where one decides; task messages
                           only in teams that exchange them; nothing lost to the network on perfect comms
    failures_kept          every run whose mission was not met is a completed run with every file (14.4)
    deterministic          the batch flown again: every run's report byte for byte, its events and records the
                           same but for a model call's latency (wall-clock time), its manifest but for when it ran
    resumes                runs removed from the second directory and the batch resumed on it: exactly those
                           are flown again, the same, and no other run is touched
"""

from __future__ import annotations

import filecmp
import io
import json
import os
from typing import Any

from .architecture import load_architecture
from .batch import BATCH_FILE, INDEX, read_index
from .conditions import load_network
from .events import EVENT_TYPES, read_events, without_wall_clock
from .experiment import PERFECT, Batch, load_failure, parse_planner
from .experiment_run import EVENTS, MANIFEST, RECORDS, REPORT
from .scenarios import load_scenario

CHECKS = ("unattended", "one_directory_per_run", "manifests_complete", "every_event_type", "events_well_formed",
          "as_configured", "failures_kept", "deterministic", "resumes")
VOLATILE = ("started", "finished", "wall_s")
NETWORK_LOSSES = ("lost", "rate_limited", "partitioned", "out_of_range")
TASK_EVENTS = ("TASK_ANNOUNCED", "TASK_BID")


def _json(path: str) -> Any:
    with io.open(path, encoding="utf-8") as h:
        return json.load(h)


def manifest_problems(m: dict[str, Any]) -> list[str]:
    p = []
    for k in ("run_id", "config", "files", "code", "software", "started", "finished", "wall_s", "status"):
        if m.get(k) in (None, "", {}):
            p.append(f"no {k}")
    for role, f in (m.get("files") or {}).items():
        if not f.get("sha256"):
            p.append(f"file {role} ({f.get('path')}) has no digest")
    code = m.get("code") or {}
    for k in ("commit", "dirty", "agentic_uav_sha256"):
        if k not in code:
            p.append(f"code has no {k}")
    if not (m.get("software") or {}).get("python"):
        p.append("no python version")
    if m.get("status") == "completed":
        if not m.get("model") or not m.get("outcome") or m.get("error") is not None:
            p.append("completed, but no model or outcome, or an error")
    elif m.get("status") == "crashed":
        if not (m.get("error") or {}).get("traceback"):
            p.append("crashed, but no traceback")
    else:
        p.append(f"status {m.get('status')!r}")
    return p


def run_checks(batch: Batch, out_dir: str) -> dict[str, list[str]]:
    p: dict[str, list[str]] = {k: [] for k in CHECKS if k not in ("unattended", "deterministic", "resumes")}
    rows = read_index(out_dir)
    if [r["run_id"] for r in rows] != [r.run_id for r in batch.runs]:
        p["one_directory_per_run"].append("the index does not list the batch's runs, once each, in order")
    seen_types: set[str] = set()
    for run in batch.runs:
        d = os.path.join(out_dir, run.run_id)
        if not os.path.isfile(os.path.join(d, MANIFEST)):
            p["one_directory_per_run"].append(f"{run.run_id}: no directory or no manifest")
            continue
        m = _json(os.path.join(d, MANIFEST))
        p["manifests_complete"] += [f"{run.run_id}: {x}" for x in manifest_problems(m)]
        if m["config"] != run.as_json():
            p["as_configured"].append(f"{run.run_id}: the manifest's configuration is not the batch's")
        if m["status"] != "completed":
            continue
        missing = [f for f in (EVENTS, REPORT, RECORDS) if not os.path.isfile(os.path.join(d, f))]
        if missing:
            p["one_directory_per_run"].append(f"{run.run_id}: completed but missing {missing}")
            continue
        events, report = read_events(os.path.join(d, EVENTS)), _json(os.path.join(d, REPORT))
        seen_types |= {e["type"] for e in events}
        p["events_well_formed"] += [f"{run.run_id}: {x}" for x in well_formed(events, report)]
        p["as_configured"] += [f"{run.run_id}: {x}" for x in as_configured(run, events, report)]
    missing_types = [t for t in EVENT_TYPES if t not in seen_types]
    if missing_types:
        p["every_event_type"].append(f"never happened: {missing_types}")
    for r in rows:
        if r["status"] == "completed" and r["met"] is False:
            d = os.path.join(out_dir, r["run_id"])
            if not all(os.path.isfile(os.path.join(d, f)) for f in (MANIFEST, EVENTS, REPORT, RECORDS)):
                p["failures_kept"].append(f"{r['run_id']}: not met, and not every file kept")
    return p


def well_formed(events: list[dict[str, Any]], report: dict[str, Any]) -> list[str]:
    p = []
    if [e["t"] for e in events] != sorted(e["t"] for e in events):
        p.append("events not in time order")
    if not events or events[0]["type"] != "MISSION_STARTED" or events[0]["t"] != 0:
        p.append("the first event is not MISSION_STARTED at 0")
    starts = [e for e in events if e["type"] == "MISSION_STARTED"]
    ends = [e for e in events if e["type"] == "MISSION_COMPLETED"]
    if len(starts) != 1 or len(ends) != 1:
        p.append(f"{len(starts)} starts and {len(ends)} completions")
    elif ends[0]["met"] != report["met"] or ends[0]["success"] != report["report"]["success"]:
        p.append("the completion event disagrees with the report")
    skills = lambda kind: sorted((e["drone"], e["serial"]) for e in events if e["type"] == kind)  # noqa: E731
    if skills("SKILL_STARTED") != skills("SKILL_COMPLETED"):
        p.append("a skill started without its end, or ended without its start")
    sent = [e["message_id"] for e in events if e["type"] == "MESSAGE_SENT"]
    if any(not isinstance(e["bytes"], int) or isinstance(e["bytes"], bool) or e["bytes"] <= 0
           for e in events if e["type"] == "MESSAGE_SENT"):
        p.append("a message whose size is not a positive number of bytes")
    if len(sent) != len(set(sent)):
        p.append("a message sent twice")
    stray = {e["message_id"] for e in events if e["type"] in ("MESSAGE_RECEIVED", "MESSAGE_DROPPED")} - set(sent)
    if stray:
        p.append(f"{len(stray)} deliveries of messages never sent")
    unknown = {e["type"] for e in events} - set(EVENT_TYPES)
    if unknown:
        p.append(f"unknown event types {sorted(unknown)}")
    return p


def as_configured(run: Any, events: list[dict[str, Any]], report: dict[str, Any]) -> list[str]:
    p = []
    arch, sc, fail = load_architecture(run.architecture), load_scenario(run.scenario), load_failure(run.failure)
    start = events[0]
    if (start.get("architecture"), start.get("network"), start.get("failure"), start.get("seed"),
            start.get("planner"), start.get("scenario")) != (run.architecture, run.network, run.failure, run.seed,
                                                             run.planner, sc.scenario_id):
        p.append("the start event is not the configuration")
    rep = report["report"]
    if (rep["scenario_id"], rep["random_seed"]) != (sc.scenario_id, run.seed):
        p.append("the judge judged another scenario or seed")
    roster = {v.id for v in sc.vehicles} | ({"base"} if arch.team == "central" else set())   # A's controller talks
    if {e["drone"] for e in events if e["drone"] is not None} - roster:
        p.append("events from a drone not in the scenario (or the base, outside team A)")
    by = lambda kind: [e for e in events if e["type"] == kind]  # noqa: E731
    faults = by("FAULT_INJECTED")
    if {e["drone"] for e in faults if e["fault"] == "stop"} != set(fail.stop):
        p.append("the drones stopped are not the failure profile's")
    injected = [e for e in faults if e["fault"] == "injection"]
    if bool(injected) != (fail.injection is not None) or any(not e["fired"] for e in injected):
        p.append("the injection is not the failure profile's, or never fired")
    if fail.injection is not None and not by("GUARDIAN_INTERVENED"):
        p.append("an unsafe proposal, and no guardian intervened")
    parts = [e for e in faults if e["fault"] == "partition"]
    net = None if run.network == PERFECT or arch.perfect_comms else load_network(run.network)
    if len(parts) != (len(net.partitions) if net is not None else 0):
        p.append("the partitions are not the network profile's")
    if bool(by("LLM_CALLED")) != (arch.decider == "llm" and parse_planner(run.planner).kind != "none"):
        p.append("a model consulted where none decides, or never where one does")
    if arch.team != "decentralized" and any(by(k) for k in TASK_EVENTS):
        p.append(f"task announcements or bids in a {arch.team} team")
    if arch.team == "decentralized" and not any(by(k) for k in TASK_EVENTS):
        p.append("a decentralized team that never bid")
    if arch.team == "central" and not any(e.get("by") == "base" for e in by("TASK_ASSIGNED")):
        p.append("a central team whose base assigned nothing")
    losses = [e for e in by("MESSAGE_DROPPED") if e["why"] in NETWORK_LOSSES]
    if net is None and losses:
        p.append(f"{len(losses)} messages lost to a network that is perfect for this run")
    if net is not None and net.loss_probability > 0 and not losses:
        p.append("a lossy network, and nothing lost")
    if arch.team == "scripted" and any(by(k) for k in ("MESSAGE_SENT", "DECISION_PROPOSED")):
        p.append("Phase 4's plan sent messages or made decisions")
    return p


def compare_batches(a: str, b: str, runs: list[str]) -> list[str]:
    """What differs between two directories of one batch: every run's files, its manifest but for when it ran."""
    p = []
    for rid in runs:
        for f in (EVENTS, REPORT, RECORDS):
            fa, fb = os.path.join(a, rid, f), os.path.join(b, rid, f)
            if os.path.isfile(fa) != os.path.isfile(fb):
                p.append(f"{rid}: {f} differs")
            elif os.path.isfile(fa) and not filecmp.cmp(fa, fb, shallow=False) and                     (f == REPORT or without_wall_clock(_content(fa)) != without_wall_clock(_content(fb))):
                p.append(f"{rid}: {f} differs")
        ma, mb = (_json(os.path.join(x, rid, MANIFEST)) for x in (a, b))
        if {k: v for k, v in ma.items() if k not in VOLATILE} != {k: v for k, v in mb.items() if k not in VOLATILE}:
            p.append(f"{rid}: the manifest differs beyond when it ran")
    ia = [{k: v for k, v in r.items() if k != "wall_s"} for r in read_index(a)]
    ib = [{k: v for k, v in r.items() if k != "wall_s"} for r in read_index(b)]
    if ia != ib:
        p.append("the indexes differ")
    ba, bb = _json(os.path.join(a, BATCH_FILE)), _json(os.path.join(b, BATCH_FILE))
    if ba["batch"] != bb["batch"] or ba["source_sha256"] != bb["source_sha256"]:
        p.append("the batch files differ")
    return p


def _content(path: str) -> Any:
    """A run file's content: the event log's lines, or a (compressed) JSON document."""
    import gzip
    if path.endswith(".jsonl.gz"):
        with gzip.open(path, "rt", encoding="utf-8") as h:
            return [json.loads(line) for line in h]
    opener = gzip.open if path.endswith(".gz") else io.open
    with opener(path, "rt", encoding="utf-8") as h:
        return json.load(h)


def manifests_of(out_dir: str, runs: list[str]) -> dict[str, bytes]:
    out = {}
    for rid in runs:
        with io.open(os.path.join(out_dir, rid, MANIFEST), "rb") as h:
            out[rid] = h.read()
    return out


__all__ = ["CHECKS", "run_checks", "compare_batches", "manifests_of", "manifest_problems", "well_formed",
           "as_configured", "INDEX"]
