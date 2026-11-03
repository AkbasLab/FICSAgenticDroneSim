"""Run one ExperimentConfig and record everything about it.

run_experiment() makes <out_root>/<experiment_id>/ holding config.json, manifest.json,
events.jsonl and results.json, so a run can be repeated and audited later. The fleet
itself is still flown by team_runner.run_team_threaded.
"""
import json
import os
import platform
import subprocess
import sys
import time
import traceback
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..agents.comms_estimator import CommsEstimator
from ..coordination.comms_conditions import BY_NAME
from ..coordination.message_bus import MessageBus
from ..coordination.network_model import NetworkModel
from ..coordination.tasks import TaskStatus
from ..evaluation.metrics import score_run
from ..simulator.kinematic_mock_adapter import KinematicMockVehicleAdapter
from ..telemetry.recorder import SAMPLE_RATE_HZ, TelemetryRecorder
from .event_log import Event, EventLog, EventType, derive_events
from .experiment_config import ExperimentConfig, build_scenario
from .team_runner import run_team_threaded, run_team_with_faults

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DEFAULT_OUT_ROOT = os.path.join(ROOT, "runs", "experiments")


class ExperimentResult:
    def __init__(self, config: ExperimentConfig, directory: str,
                 runs: Optional[List[dict]] = None, aggregate: Optional[dict] = None,
                 error: Optional[str] = None):
        self.config = config
        self.directory = directory
        self.runs = runs or []
        self.aggregate = aggregate or {}
        self.error = error

    @property
    def ok(self) -> bool:
        return self.error is None

    def summary(self) -> str:
        status = "ok" if self.ok else "FAILED"
        return (f"{self.config.experiment_id}: {len(self.runs)}/{self.config.repeats} "
                f"runs, {status}")


def _run_once(scenario, monitor: bool, mock_speed_mps: float, repeat: int, kill=None,
              network=None, estimates: bool = False, policy=None, save_dir=None,
              leg_planner=None, leg_timeout_s: float = 30.0):
    """One fleet run. Returns (metrics, events); metrics has the shape the
    dynamic-zone study has always saved."""
    adapters = {d.name: KinematicMockVehicleAdapter(d.name, speed_mps=mock_speed_mps)
                for d in scenario.drones}
    offsets = {d.name: d.spawn_offset for d in scenario.drones}
    recorder = TelemetryRecorder(adapters, world_offsets=offsets)
    rec_start = time.monotonic()
    recorder.start()
    start = time.monotonic()
    if network:
        bus = MessageBus(network_model=NetworkModel(BY_NAME[network[0]], seed=network[1]))
    else:
        bus = MessageBus()
    estimators = ({d.name: CommsEstimator() for d in scenario.drones}
                  if estimates else None)
    if policy:
        from ..agents.llm_policy import make_policy_factory
        factory, policies = make_policy_factory(policy[0], scenario, timeout_s=policy[1])
        reports, agents, _bus, _assign = run_team_with_faults(
            scenario, adapters, bus=bus, heartbeat_interval_s=2.0, policy_factory=factory)
    elif kill:
        reports, agents, _bus, assignment = run_team_with_faults(
            scenario, adapters, bus=bus, kill_name=kill[0], kill_at_s=kill[1])
    else:
        reports, agents, _bus = run_team_threaded(
            scenario, adapters, bus=bus,
            agent_kwargs={"zone_monitor": monitor, "leg_planner": leg_planner, "leg_timeout_s": leg_timeout_s},
            comms_estimators=estimators)
    elapsed = time.monotonic() - start
    # one more sample before stopping: at 5 Hz the last sample can be 0.2 s stale, which
    # for a drone moving at 15 m/s is ~3 m and made landed drones read as "not home"
    time.sleep(2.0 / SAMPLE_RATE_HZ)
    recorder.stop()

    # The recorder's clock starts before the agents' (allocation runs first), but zones
    # are scheduled in the agents' mission time. clock_off[n] = agent start - recorder start.
    clock_off = {n: (a._run_start - rec_start) if getattr(a, "_run_start", None) is not None
                 else 0.0 for n, a in agents.items()}
    agent_log = _to_agent_clock(recorder.log, clock_off)
    score = score_run(scenario, agent_log, elapsed)
    # exposure on the agents clock, the one zone schedules run on
    exposure_s = _exposure_s(scenario, agent_log)
    interrupts = sum(step == "zone_interrupt" for r in reports.values() for step in r.trace)
    entries = [e for a in agents.values() for e in a.guardian_log.entries]
    by_outcome, by_check = {}, {}
    for e in entries:
        by_outcome[e.outcome] = by_outcome.get(e.outcome, 0) + 1
        for name in e.failed_checks:
            by_check[name] = by_check.get(name, 0) + 1
    interventions = sum(1 for e in entries if e.outcome != "approve")
    metrics = {
        "guardian": {
            "commands": len(entries),
            "interventions": interventions,
            "intervention_rate": round(interventions / len(entries), 3) if entries else 0.0,
            "by_outcome": by_outcome,
            "failed_checks": by_check,
            "steer_outs": sum(1 for e in entries if e.fallback == "exit_zone"),
            "steer_out_distance_m": round(sum(e.move_m for e in entries
                                              if e.move_m is not None), 1),
            "zone_interrupts": interrupts,
        },
        "mission": {
            "coverage": round(score.coverage_fraction, 3),
            "targets_found": score.targets_found,
            "no_fly_violations": score.no_fly_violations,
            "zone_exposure_s": round(exposure_s, 1),
            "clock_offset_s": {n: round(v, 2) for n, v in clock_off.items()},
            "separation_violations": len(score.separation_violations),
            "mission_s": round(elapsed, 1),
            "all_home": score.all_home,
            "overall_pass": score.overall_pass,
        },
    }
    events = derive_events(agents, reports, scenario, agent_log, repeat)
    if policy:
        decisions = [r for p in policies.values() for r in p.records]
        fallbacks = sum(1 for r in decisions if r.source == "fallback")
        metrics["model"] = {
            "decisions": len(decisions),
            "fallbacks": fallbacks,
            "fallback_rate": round(fallbacks / len(decisions), 3) if decisions else 0.0,
        }
        if save_dir:
            from .llm_log import save_run
            save_run(save_dir, policies, agents, policy[2])
    if network:
        metrics["comms"] = comms_summary(scenario, agents, reports, bus, estimators)
    if kill:
        metrics["recovery"] = recovery_summary(scenario, agents, reports, assignment, kill)
        events.append(Event(EventType.DRONE_KILLED, repeat, kill[1], kill[0]))
    telemetry = {name: [[round(float(s.t), 2)] + [round(float(c), 2) for c in s.position]
                        for s in samples]
                 for name, samples in recorder.log.items()}
    return metrics, events, telemetry


def comms_summary(scenario, agents, reports, bus, estimators) -> Dict[str, Any]:
    """Message-bus statistics for one run, plus each drone's loss estimate of its peers."""
    delivered_entries = [e for e in bus.log if e.delivered]
    sent, delivered = len(bus.log), len(delivered_entries)
    drops: Dict[str, int] = {}
    for e in bus.log:
        if not e.delivered:
            drops[e.reason] = drops.get(e.reason, 0) + 1
    out: Dict[str, Any] = {
        "sent": sent,
        "delivered": delivered,
        "delivery_rate_pct": (delivered / sent * 100.0) if sent else 0.0,
        "mean_delay_s": (sum(e.delay_s for e in delivered_entries) / delivered
                         if delivered else 0.0),
        "drops": drops,
        # Sector assignment is static here (run_team_threaded, on purpose), so this counts
        # drones that ran their own mission to completion, not who won a sector.
        "sectors_done": sum(1 for r in reports.values()
                            if r.trace and r.trace[-1] == "skill_succeeded->done"),
        "sectors_total": len(scenario.sectors),
    }
    if estimators:
        est_out = {}
        for name, est in estimators.items():
            losses = {peer: est.estimated_loss_rate(peer) for peer in agents if peer != name}
            est_out[name] = {p: v for p, v in losses.items() if v is not None}
        out["loss_estimates"] = est_out
    return out


def recovery_summary(scenario, agents, reports, assignment, kill) -> Dict[str, Any]:
    """Which sectors the survivors finished after kill=(name, at_s) was switched off.
    Union of COMPLETE across every survivor's own board: one board is frozen at
    whatever its agent last observed, and a final sector_id shows only the last
    sector an agent worked."""
    done = set()
    for name, agent in agents.items():
        if name == kill[0]:
            continue
        for t in agent.task_board.tasks.values():
            if t.status == TaskStatus.COMPLETE:
                done.add(t.sector_id)
    drones = {}
    for name, rep in reports.items():
        drones[name] = {
            "target_found": str(rep.target_found),
            "battery_frac_at_end": float(rep.battery_frac_at_end),
            "killed": name == kill[0] and bool(rep.trace) and "killed" in rep.trace[-1],
        }
    return {
        "killed": kill[0],
        "kill_at_s": kill[1],
        "sectors_total": len(scenario.sectors),
        "sectors_completed": len(done),
        "completed_sector_ids": sorted(done),
        "assignment": dict(assignment),
        "drones": drones,
    }


def _save_dir(base: Optional[str], i: int, repeats: int) -> Optional[str]:
    if not base or repeats == 1:
        return base
    return os.path.join(base, f"repeat_{i}")


def _aggregate(runs: List[dict]) -> Dict[str, Any]:
    """Mean of every numeric field across repeats, plus the overall pass rate."""
    out: Dict[str, Any] = {}
    for group in ("guardian", "mission", "recovery", "comms", "model"):
        if group not in runs[0]:
            continue
        means = {}
        for key, v in runs[0][group].items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                means[key] = round(sum(r[group][key] for r in runs) / len(runs), 3)
        out[group] = means
    out["pass_rate"] = round(sum(bool(r["mission"]["overall_pass"]) for r in runs)
                             / len(runs), 3)
    return out


def _git(*args: str) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True,
                                       stderr=subprocess.DEVNULL).strip()
    except Exception:
        return "unknown"


def _write_json(path: str, data: Any) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def _make_backend(cfg: ExperimentConfig):
    if cfg.policy == "scripted":
        from ..agents.llm_backends import ScriptedBackend
        return ScriptedBackend()
    from ..agents.ollama_backend import OllamaBackend
    return OllamaBackend(cfg.model)


def run_experiment(cfg: ExperimentConfig, out_root: str = DEFAULT_OUT_ROOT, backend=None,
                   llm_save_dir: Optional[str] = None) -> ExperimentResult:
    """Run every repeat of cfg and write its folder. An existing folder for the same
    experiment_id raises FileExistsError, so earlier results are never overwritten."""
    cfg.validate()
    policy = None
    if cfg.policy != "deterministic":
        backend = backend or _make_backend(cfg)
        card = backend.card() if cfg.policy == "ollama" else None
        policy = (backend, cfg.llm_timeout_s, card.to_dict() if card else None)
    directory = os.path.join(out_root, cfg.experiment_id)
    os.makedirs(directory)
    _write_json(os.path.join(directory, "config.json"), cfg.to_dict())
    _write_json(os.path.join(directory, "manifest.json"), {
        "started_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": _git("rev-parse", "--short", "HEAD"),
        "git_dirty": _git("status", "--porcelain") not in ("", "unknown"),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "noclip": cfg.noclip,
        "policy": cfg.policy,
        "model": cfg.model if cfg.policy == "ollama" else None,
        "model_card": policy[2] if policy else None,
        "engine": ("team_runner.run_team_with_faults" if (cfg.kill_vehicle or policy)
                   else "team_runner.run_team_threaded"),
    })

    log = EventLog()
    log.emit(EventType.RUN_START, experiment_id=cfg.experiment_id)
    monitor = cfg.zone_monitor == "tick"
    kill = (cfg.kill_vehicle, cfg.kill_at_s) if cfg.kill_vehicle else None
    network = (cfg.network_profile, cfg.seed) if cfg.network_profile else None
    runs: List[dict] = []
    error: Optional[str] = None
    leg_planner = None
    if cfg.leg_planner == "navrl":
        from ..planners.navrl_planner import NavRLPlanner
        leg_planner = NavRLPlanner()
    try:
        for i in range(cfg.repeats):
            metrics, events, telemetry = _run_once(build_scenario(cfg), monitor,
                                        cfg.mock_speed_mps, i, kill, network, cfg.comms_estimates,
                                        policy, _save_dir(llm_save_dir, i, cfg.repeats),
                                        leg_planner, cfg.leg_timeout_s)
            runs.append(metrics)
            _write_json(os.path.join(directory, f"telemetry_{i}.json"), telemetry)
            log.extend(events)
    except Exception:
        error = traceback.format_exc(limit=4)
    log.emit(EventType.RUN_END, ok=error is None, repeats_done=len(runs))
    log.write(os.path.join(directory, "events.jsonl"))

    aggregate = _aggregate(runs) if runs else {}
    _write_json(os.path.join(directory, "results.json"), {
        "config": cfg.to_dict(), "runs": runs, "aggregate": aggregate,
        "event_counts": log.counts(), "error": error})
    return ExperimentResult(cfg, directory, runs, aggregate, error)


def _to_agent_clock(log, clock_off):
    """Copy of the recorder log with each drone timestamps moved to its agents mission clock, which is what zone schedules use."""
    return {n: [replace(x, t=x.t - clock_off.get(n, 0.0)) for x in smps]
            for n, smps in log.items()}


def _exposure_s(scenario, log):
    """Seconds spent inside any zone while it was active, summed over drones."""
    return sum(1 for samples in log.values() for smp in samples
               if any(z.contains(smp.position[0], smp.position[1], smp.t)
                      for z in scenario.no_fly_zones)) / SAMPLE_RATE_HZ
