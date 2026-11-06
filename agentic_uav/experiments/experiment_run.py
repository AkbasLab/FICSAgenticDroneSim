"""Phase 14: one run, one result directory, kept whatever happens (AUV-14, 14.2 and 14.4).

    row = run_one(config, "runs/experiments/<batch>")      # flies it, writes <batch>/<run_id>/, returns its row

A run's directory holds:

    manifest.json      written LAST, so a directory without one is unfinished (and `--resume` flies it again):
                       the configuration; every configuration file read, with its digest; the code (commit,
                       dirty flag, package digest); software versions; the model and its parameters; start
                       and finish; the status -- completed, or crashed with the error and its traceback;
                       and the outcome (the mission met or not)
    report.json        the judge's report (AUV-05's criteria, components, facts) and the flight's own summary
    events.jsonl.gz    the 19-type event log (`events.py`)
    records.json.gz    the raw records: each drone's policy, guardian and model logs, skills started, the base
                       controller's log -- what a failure taxonomy needs beyond the events

14.4: NOTHING IS DISCARDED. A mission not met is a completed run like any
other. A run that raises is caught: its manifest records "crashed", the error
and the traceback, and the batch goes on. Only the manifest carries wall-clock
times, so the rest of a directory is byte-for-byte the same when the run is
flown again.
"""

from __future__ import annotations

import gzip
import io
import json
import os
import platform
import sys
import time
import traceback
from typing import Any

from .architecture import fly_architecture, load_architecture
from .conditions import load_network
from .events import flight_events, write_events
from .experiment import (PERFECT, ExperimentConfig, injection_named, load_failure, parse_planner, replay_label,
                         replay_records)
from .provenance import REPO_ROOT, file_digest, provenance

MANIFEST, REPORT, EVENTS, RECORDS = "manifest.json", "report.json", "events.jsonl.gz", "records.json.gz"
KEEPOUT = os.path.join(REPO_ROOT, "configs", "keepout", "default.toml")
SHARED = {"allocation": ("configs", "allocation", "default.toml"), "recovery": ("configs", "recovery", "default.toml"),
          "guardian": ("configs", "guardian", "default.toml"), "keep_out": ("configs", "keepout", "default.toml")}
STATUSES = ("completed", "crashed")


def _rel(path: str) -> str:
    try:
        rel = os.path.relpath(path, REPO_ROOT)
    except ValueError:
        return path.replace("\\", "/")
    return (path if rel.startswith("..") else rel).replace("\\", "/")


def software() -> dict[str, Any]:
    from importlib.metadata import PackageNotFoundError, version
    out: dict[str, Any] = {"python": sys.version.split()[0], "platform": platform.platform()}
    for pkg in ("numpy", "ollama", "airsim"):
        try:
            out[pkg] = version(pkg)
        except PackageNotFoundError:
            out[pkg] = None
    return out


def complete(run_dir: str) -> bool:
    return os.path.isfile(os.path.join(run_dir, MANIFEST))


def _write_json(path: str, obj: Any) -> None:
    tmp = path + ".tmp"
    with io.open(tmp, "w", encoding="utf-8", newline="\n") as h:
        json.dump(obj, h, indent=1, sort_keys=True, default=str)
        h.write("\n")
    os.replace(tmp, path)


def _write_gz_json(path: str, obj: Any) -> None:
    tmp = path + ".tmp"
    with io.open(tmp, "wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
            gz.write(json.dumps(obj, sort_keys=True, default=str).encode("utf-8"))
    os.replace(tmp, path)


def _injection_hooks(injection: Any, scenario: Any, limits: Any) -> tuple[Any, Any, dict[str, Any]]:
    """Phase 11's injector for one drone, as `fly_architecture` hooks (as in `guardian_exit.fly_injected`)."""
    from ..control.scripted import ALTITUDE_STEP_M, BASE_ALTITUDE_M
    from .guardian_exit import Injector, operating_box
    box = operating_box(scenario.brief(), limits.fence_margin_m)
    layers = {v.id: BASE_ALTITUDE_M + i * ALTITUDE_STEP_M for i, v in enumerate(scenario.vehicles)}
    held: dict[str, Any] = {}
    clocks: dict[str, Any] = {}

    def wrap_handle(drone: str, handle: Any, guardian: Any) -> Any:
        clocks[drone] = handle.clock
        if drone == injection.drone and injection.style in ("conflict", "direct"):
            held["injector"] = Injector(injection, None, handle.clock, handle.clock.now(), box, layers[drone], False)
            return held["injector"].handle(handle)
        return handle

    def wrap_policy(drone: str, policy: Any) -> Any:
        if drone == injection.drone and injection.style not in ("conflict", "direct"):
            clock = clocks[drone]
            held["injector"] = Injector(injection, policy, clock, clock.now(), box, layers[drone],
                                        injection.channel == "llm")
            return held["injector"]
        return policy

    return wrap_policy, wrap_handle, held


def _ask(planner: Any, run: ExperimentConfig, stop: dict[str, float], endpoint: str | None) -> tuple[Any, dict]:
    from ..planners.llm_ask import EchoAsk, OllamaAsk, ReplayAsk
    if planner.kind == "none":
        return None, {"planner": "none"}
    if planner.kind == "echo":
        return EchoAsk(), {"planner": "echo", "model": "the rule's own choice (no model)"}
    if planner.kind == "replay":
        rec = replay_records(planner.arg)[(run.seed, replay_label(stop))]
        return ReplayAsk(rec["records"]), {"planner": planner.text, "model": rec.get("model"),
                                           "replayed_flight": [run.seed, replay_label(stop)]}
    from .llm import load_llm
    cfg = load_llm(planner.arg)
    if endpoint is None:
        raise ValueError(f"planner {planner.text}: no model endpoint given")
    return OllamaAsk(cfg.model, endpoint, cfg.options, cfg.timeout_s), {"planner": planner.text,
                                                                        "llm": cfg.as_json(), "endpoint": endpoint}


def fly_config(run: ExperimentConfig, endpoint: str | None = None) -> tuple[Any, Any, Any, dict | None, dict]:
    """Fly one configuration. Returns the flight, the scenario, the failure profile, the injection's record, and
    what the model was."""
    from ..coordination.keepout import parse_keepout
    from .allocation import load_allocation
    from .guardian_exit import load_guardian
    from .recovery import load_recovery
    from .runner import load_toml
    from .scenarios import load_scenario
    arch = load_architecture(run.architecture)
    scenario = load_scenario(run.scenario)
    failure = load_failure(run.failure)
    limits = load_guardian()
    network = None if run.network == PERFECT else load_network(run.network)
    ask, model = _ask(parse_planner(run.planner), run, failure.stop, endpoint)
    hooks: dict[str, Any] = {}
    held: dict[str, Any] = {}
    if failure.injection is not None:
        import dataclasses
        wp, wh, held = _injection_hooks(injection_named(failure.injection),
                                        dataclasses.replace(scenario, random_seed=run.seed), limits)
        hooks = {"wrap_policy": wp, "wrap_handle": wh}
    flight = fly_architecture(arch, scenario, run.seed, load_allocation(), load_recovery(), limits,
                              parse_keepout(load_toml(KEEPOUT), KEEPOUT), failure.stop or None, network=network,
                              ask=ask, **hooks)
    record = held["injector"].record if "injector" in held else None
    return flight, scenario, failure, record, model


def _report(flight: Any) -> dict[str, Any]:
    r = flight.run
    team = getattr(r, "team", None)
    rep = r.report if team is None else team.report
    out = {"met": bool(r.met), "report": rep.as_json()}
    if team is not None:
        out.update({"team_kind": r.team_kind, "stopped": r.stopped, "searched": r.searched,
                    "finished": team.finished})
    return out


def _records(flight: Any, injection_record: dict | None) -> dict[str, Any]:
    r = flight.run
    if getattr(r, "team", None) is None:
        return {"scripted": r.as_json() if hasattr(r, "as_json") else None}
    return {"policies": r.policies, "guardians": r.guardians, "executed": r.executed, "controller": r.controller,
            "llm": flight.llm, "injection": injection_record}


def run_one(run: ExperimentConfig, out_root: str, endpoint: str | None = None) -> dict[str, Any]:
    """Fly `run` into `out_root/<run_id>/`, unless it is already complete there. Never raises for the run's sake."""
    run_dir = os.path.join(out_root, run.run_id)
    if complete(run_dir):
        return index_row(run_dir)
    os.makedirs(run_dir, exist_ok=True)
    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    wall = time.perf_counter()
    manifest: dict[str, Any] = {
        "run_id": run.run_id, "config": run.as_json(),
        "files": {role: {"path": _rel(p), "sha256": file_digest(p)} for role, p in
                  {**run.files(), **{k: os.path.join(REPO_ROOT, *v) for k, v in SHARED.items()}}.items()},
        "code": provenance(), "software": software(), "started": started}
    status, error, outcome, written = "crashed", None, None, []
    try:
        flight, scenario, failure, record, model = fly_config(run, endpoint)
        manifest["model"] = model
        events = flight_events(flight, run, scenario, failure, record)
        n = write_events(events, os.path.join(run_dir, EVENTS + ".tmp"))
        os.replace(os.path.join(run_dir, EVENTS + ".tmp"), os.path.join(run_dir, EVENTS))
        report = _report(flight)
        _write_json(os.path.join(run_dir, REPORT), report)
        _write_gz_json(os.path.join(run_dir, RECORDS), _records(flight, record))
        written = [EVENTS, REPORT, RECORDS]
        rep = report["report"]
        outcome = {"met": report["met"], "success": rep["success"], "completion_s": rep["completion_s"], "events": n}
        status = "completed"
    except Exception as exc:            # 14.4: a crashed run is kept, with why
        error = {"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()}
    manifest.update({"finished": time.strftime("%Y-%m-%dT%H:%M:%S"), "wall_s": round(time.perf_counter() - wall, 3),
                     "status": status, "outcome": outcome, "error": error, "files_written": written + [MANIFEST]})
    _write_json(os.path.join(run_dir, MANIFEST), manifest)
    return index_row(run_dir)


def index_row(run_dir: str) -> dict[str, Any]:
    with io.open(os.path.join(run_dir, MANIFEST), encoding="utf-8") as h:
        m = json.load(h)
    c, o = m["config"], m["outcome"] or {}
    return {"run_id": m["run_id"], "index": c["index"], "experiment": c["experiment_id"],
            "architecture": c["architecture"], "scenario": c["scenario"], "network": c["network"],
            "failure": c["failure"], "seed": c["seed"], "planner": c["planner"], "status": m["status"],
            "met": o.get("met"), "completion_s": o.get("completion_s"), "events": o.get("events"),
            "error": None if m["error"] is None else m["error"]["type"], "wall_s": m["wall_s"]}
