"""Run one experiment from one config, into one result directory (Phase 14).

    results/exp_0042/
        manifest.json       what produced the run, and whether it finished
        config.yaml         the configuration, copied verbatim
        events.jsonl        the structured event stream
        result.json         the metrics
        llm/Drone1.json     every prompt and raw response, when a model was used
        error.txt           the traceback, if it failed

**A failed run still produces all of this** (14.4). That is the whole design
constraint of this module. A crash part-way through a mission is often the most
informative run in a batch - it is where an agentic system did something nobody
anticipated - and a runner that discards it, or that dies before writing the
events, destroys the evidence. So the directory is created first, the manifest
is written before the mission starts and rewritten after it ends, and the event
stream is flushed in a `finally` block regardless of how the run terminated.
"""

import json
import os
import shutil
import time
import traceback
from dataclasses import asdict
from typing import Any, Dict, Optional

from . import architectures as arch
from .events import EventLog, EventType, derive
from .experiment_config import ExperimentConfig, Manifest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))


class ExperimentResult:
    """What the batch runner needs to report, whether or not the run worked."""

    def __init__(self, config, directory, manifest, result=None, error=None):
        self.config = config
        self.directory = directory
        self.manifest = manifest
        self.result = result
        self.error = error

    @property
    def ok(self):
        return self.error is None

    def summary(self):
        if not self.ok:
            return (f"{self.config.experiment_id}: FAILED "
                    f"({self.manifest.error_type}: "
                    f"{(self.manifest.error_message or '')[:60]})")
        r = self.result
        return (f"{self.config.experiment_id}: coverage {r.coverage:.2f}  "
                f"home {r.drones_home}  dup {r.duplicated_sectors}  "
                f"t {r.mission_time_s:.0f}s")


def _backend_for(cfg, root):
    """Build the planner named in the config.

    `scripted` is the deterministic control used for plumbing checks; anything
    else is a real model. The model card is recorded in the manifest so a run
    can never be mistaken for one produced by a different planner.
    """
    if arch.spec(cfg.architecture_key).policy != "llm":
        return None, {}
    name = (cfg.planner or "scripted").lower()
    if name in ("scripted", "none", "control"):
        import sys
        sys.path.insert(0, os.path.join(root, "scripts"))
        from run_llm_agents import sensible_model
        from ..agents.llm_backends import ScriptedBackend
        backend = ScriptedBackend(default=sensible_model)
    else:
        from ..agents.llm_backends import make_backend
        provider = "ollama"
        model = cfg.planner
        if ":" in name and name.split(":")[0] in ("ollama", "gemini", "mistral"):
            provider, model = cfg.planner.split(":", 1)
        elif "gemini" in name:
            provider = "gemini"
        backend = make_backend(provider, model=model)
    card = backend.card() if hasattr(backend, "card") else None
    return backend, (card.as_dict() if card else {})


def run_experiment(cfg: ExperimentConfig, out_root="results", root=ROOT,
                   overwrite=True) -> ExperimentResult:
    """Execute one configuration and write a complete result directory."""
    directory = os.path.join(out_root, cfg.experiment_id)
    if overwrite and os.path.isdir(directory):
        shutil.rmtree(directory)
    os.makedirs(directory, exist_ok=True)

    manifest = Manifest.begin(cfg, root)
    # written before anything can fail, so a run that dies on the first step
    # still leaves a record of what it was trying to do
    manifest.write(os.path.join(directory, "manifest.json"))
    _copy_config(cfg, directory)

    log = EventLog()
    started = time.monotonic()
    built = result = error = None

    try:
        from ..simulator.mock_adapter import MockVehicleAdapter
        from ..simulator.scenario_manager import load_scenario

        scenario = load_scenario(cfg.scenario_path(root))
        _check_team_size(cfg, scenario, manifest)
        backend, model_card = _backend_for(cfg, root)
        manifest.model = model_card

        built = arch.build(
            cfg.architecture_key, scenario,
            lambda _vid: MockVehicleAdapter(0.0),
            condition=cfg.network_profile, seed=cfg.random_seed,
            backend=backend, heartbeat_interval_s=cfg.heartbeat_s)

        log.emit(EventType.MISSION_STARTED, t=0.0,
                 experiment_id=cfg.experiment_id,
                 architecture=cfg.architecture_key,
                 scenario=cfg.scenario, seed=cfg.random_seed,
                 network_profile=built.condition,
                 team_size=len(built.agents),
                 planner=cfg.planner)
        for vid, when in sorted(cfg.faults.items()):
            log.emit(EventType.FAULT_INJECTED, t=when, vehicle=vid,
                     fault="vehicle_stopped", scheduled_at=when,
                     profile=cfg.failure_profile)

        result = arch.run(built, max_total_steps=cfg.max_steps,
                          stop_at=cfg.faults)

        log.emit(EventType.MISSION_COMPLETED, t=result.mission_time_s,
                 coverage=result.coverage,
                 sectors_searched=result.sectors_searched,
                 all_landed=result.all_landed,
                 drones_home=result.drones_home,
                 duplicated_sectors=result.duplicated_sectors,
                 total_steps=result.total_steps)

    except BaseException as exc:                                # noqa: BLE001
        # Deliberately broad. A crashed run is data (14.4), and the one thing
        # that must not happen is losing the events that led up to it.
        error = exc
        log.emit(EventType.MISSION_COMPLETED,
                 t=_last_clock(built), completed=False,
                 error=type(exc).__name__, message=str(exc)[:300])

    finally:
        # Everything below runs whether the mission finished, crashed, or was
        # interrupted. Derivation is itself guarded: a half-built run can have
        # logs in odd states, and failing to write the stream because the
        # translation tripped would defeat the point.
        try:
            if built is not None:
                derive(log, built, result)
        except Exception as derive_error:                       # noqa: BLE001
            manifest.warnings.append(
                f"event derivation failed: {type(derive_error).__name__}: "
                f"{derive_error}")

        log.write(os.path.join(directory, "events.jsonl"))
        manifest.event_counts = log.counts()
        manifest.finish(started, completed=error is None, error=error)

        if result is not None:
            with open(os.path.join(directory, "result.json"), "w",
                      encoding="utf-8") as f:
                json.dump(result.as_row(), f, indent=1, default=str)

        if built is not None and built.policies:
            _save_llm_transcripts(built, directory)

        if error is not None:
            with open(os.path.join(directory, "error.txt"), "w",
                      encoding="utf-8") as f:
                f.write("".join(traceback.format_exception(
                    type(error), error, error.__traceback__)))

        manifest.write(os.path.join(directory, "manifest.json"))

    return ExperimentResult(cfg, directory, manifest, result, error)


def _copy_config(cfg, directory):
    """Copy the config verbatim when there is a file, else serialise it.

    Verbatim matters: a config may carry comments explaining why a value was
    chosen, and those are part of the record.
    """
    source = getattr(cfg, "_source_path", None)
    target = os.path.join(directory, "config.yaml")
    if source and os.path.isfile(source):
        shutil.copyfile(source, target)
        return
    try:
        import yaml
        with open(target, "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg.as_dict(), f, sort_keys=False)
    except Exception:                                           # noqa: BLE001
        with open(os.path.join(directory, "config.json"), "w",
                  encoding="utf-8") as f:
            json.dump(cfg.as_dict(), f, indent=1)


def _check_team_size(cfg, scenario, manifest):
    """`team_size` is in the config, but the scenario file decides the fleet.

    Rather than silently running four drones for a config that asked for six,
    this records a warning in the manifest. The scenario wins because vehicles
    need start pads, batteries and sectors that only it defines.
    """
    actual = len(scenario.vehicles)
    if cfg.team_size and cfg.team_size != actual:
        manifest.warnings.append(
            f"config requested team_size={cfg.team_size} but scenario "
            f"'{cfg.scenario}' defines {actual} vehicles; the scenario wins")


def _last_clock(built):
    if built is None or not getattr(built, "agents", None):
        return 0.0
    return max((a.belief.now for a in built.agents), default=0.0)


def _save_llm_transcripts(built, directory):
    out = os.path.join(directory, "llm")
    os.makedirs(out, exist_ok=True)
    for vid, policy in built.policies.items():
        log = getattr(policy, "log", None)
        if log is not None and hasattr(log, "save"):
            try:
                log.save(os.path.join(out, f"{vid}.json"))
            except Exception:                                   # noqa: BLE001
                pass
