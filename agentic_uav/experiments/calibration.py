"""Communication calibration (Phase 17.3).

Choose degradation levels that produce distinguishable but not trivial outcomes.
This module sweeps a ladder of network profiles, runs the same failure scenario
under each, and classifies every level against explicit rules - so the reason
each final level was chosen is written down and reproducible, not a judgement
made while looking at a plot.

A level is rejected when it is:

  useless      communication cannot do anything: under a quarter of messages
               arrive, latency exceeds the time after which a silent teammate
               is presumed lost, or every coordinating architecture duplicates
               nearly every sector (the team behaves as if it had no radio)
  too weak     loss is too low to affect coordination: under half a duplicated
               sector per run and mission time within 15% of the loss-free level
  trivial      every architecture succeeds cleanly almost always, or fails
               almost always - the mission fails, or coordination does (no clean
               success and three-quarters of the sectors flown twice)
  flat         every seed gives the same outcome - repeated seeds would add no
               information, so no statistic could be computed from them

Everything else is *usable*. The final moderate level is the mildest usable
level on the loss axis and the final severe level the harshest level of the
contiguous usable band above it, so the two are as far apart as the band
allows while both stay meaningful.

"Clean success" here means every sector searched, every surviving drone landed
at home, and no sector flown twice.
"""

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..coordination import comms_conditions as cc
from ..coordination.network_model import NetworkProfile


@dataclass
class Level:
    name: str
    profile: NetworkProfile
    axis: str                         # loss | latency | reference
    x: float                          # the axis value (loss fraction or latency ms)


@dataclass
class LevelResult:
    level: Level
    by_arch: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    flags: List[str] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)

    @property
    def usable(self):
        return not self.flags


def load_ladder(path) -> Dict[str, Any]:
    import yaml
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def levels_from(ladder) -> List[Level]:
    from .freeze import check_seed_use
    check_seed_use(ladder.get("seeds", []), purpose="calibration")
    out = []
    la = ladder.get("loss_axis")
    if la:
        for loss in la["loss"]:
            name = f"loss{int(round(loss * 100)):02d}"
            out.append(Level(name, NetworkProfile(
                name=name, latency_ms_mean=float(la["latency_ms_mean"]),
                latency_ms_jitter=float(la["latency_ms_jitter"]),
                packet_loss_probability=float(loss)), "loss", float(loss)))
    lt = ladder.get("latency_axis")
    if lt:
        for ms in lt["latency_ms_mean"]:
            name = f"lat{int(ms)}ms"
            out.append(Level(name, NetworkProfile(
                name=name, latency_ms_mean=float(ms),
                latency_ms_jitter=float(ms) * float(lt.get("jitter_fraction", 0.2)),
                packet_loss_probability=float(lt.get("packet_loss_probability", 0.0))),
                "latency", float(ms)))
    for ref in ladder.get("reference", []) or []:
        out.append(Level(f"ref_{ref}", cc.condition(ref), "reference", float("nan")))
    return out


def _register(level):
    """Make a calibration level reachable by name for the architecture builder,
    without adding it to the frozen set of conditions."""
    cc.CONDITIONS[level.name] = level.profile
    return level.name


def run_level(level, ladder, backend_factory=None):
    from ..simulator.mock_adapter import MockVehicleAdapter
    from ..simulator.scenario_manager import load_scenario
    from . import architectures as arch
    from .experiment_config import FAILURE_PROFILES
    from .experiment_runner import ROOT
    import dataclasses
    import os

    sc = load_scenario(os.path.join(ROOT, "configs", "missions", "search_relay_001.yaml"))
    n = int(ladder.get("team_size", 4))
    sc = dataclasses.replace(sc, vehicles=list(sc.vehicles[:n]))
    team = {v.vehicle_id for v in sc.vehicles}
    faults = {v: t for v, t in FAILURE_PROFILES[ladder["failure_profile"]].items()
              if v in team}
    name = _register(level)
    res = LevelResult(level)
    for key in ladder["architectures"]:
        runs = []
        for seed in ladder["seeds"]:
            backend = backend_factory(key) if backend_factory else None
            r = arch.run_architecture(
                key, sc, lambda _v: MockVehicleAdapter(0.0), condition=name,
                seed=int(seed), backend=backend,
                heartbeat_interval_s=float(ladder.get("heartbeat_s", 8.0)),
                stop_at=faults)
            survivors = n - len(r.stopped)
            runs.append({
                "coverage": r.coverage, "dup": r.duplicated_sectors,
                "time": r.mission_time_s, "delivery": r.delivery_rate,
                "home": r.drones_home,
                "mission_ok": r.coverage == 1.0 and r.drones_home == survivors,
                "clean": (r.coverage == 1.0 and r.drones_home == survivors
                          and r.duplicated_sectors == 0)})
        res.by_arch[key] = _stats(runs)
    return res


def _stats(runs):
    def ms(k):
        v = [float(r[k]) for r in runs]
        m = sum(v) / len(v)
        sd = math.sqrt(sum((x - m) ** 2 for x in v) / (len(v) - 1)) if len(v) > 1 else 0.0
        return m, sd
    out = {"runs": len(runs)}
    for k in ("coverage", "dup", "time", "delivery", "home"):
        out[f"{k}_mean"], out[f"{k}_sd"] = ms(k)
    out["clean_rate"] = sum(1 for r in runs if r["clean"]) / len(runs)
    out["mission_ok_rate"] = sum(1 for r in runs if r["mission_ok"]) / len(runs)
    out["flat"] = len({(r["coverage"], r["dup"], round(r["time"], 1)) for r in runs}) == 1
    return out


def classify(results: List[LevelResult], ladder, coordinating=("C", "D"),
             sectors=4) -> None:
    """Attach flags and plain-language reasons to every level, in place."""
    rules = ladder["rules"]
    from ..coordination.roles import HealthMonitor
    hb = float(ladder.get("heartbeat_s", 8.0))
    presumed_lost_s = hb * HealthMonitor("x", heartbeat_interval_s=hb).unreachable_after
    base = next((r for r in results if r.level.axis == "loss" and r.level.x == 0.0), None)

    for r in results:
        arches = [a for a in coordinating if a in r.by_arch]
        if not arches:
            continue
        s = {a: r.by_arch[a] for a in arches}
        delivery = min(x["delivery_mean"] for x in s.values())
        lat_s = r.level.profile.latency_ms_mean / 1000.0

        if delivery < rules["useless_delivery_below"]:
            r.flags.append("useless")
            r.reasons.append(f"only {100 * delivery:.0f}% of messages arrive")
        if lat_s >= presumed_lost_s:
            r.flags.append("useless")
            r.reasons.append(f"latency {lat_s:.0f} s >= {presumed_lost_s:.0f} s, after "
                             f"which a silent teammate is presumed lost - every "
                             f"message arrives too late to matter")
        if all(x["dup_mean"] >= rules["useless_dup_fraction"] * sectors for x in s.values()):
            r.flags.append("useless")
            r.reasons.append("every coordinating architecture duplicates nearly every "
                             "sector - the team behaves as if it had no radio")
        if base is not None and r is not base:
            weak = all(x["dup_mean"] < rules["weak_dup_below"]
                       and abs(x["time_mean"] - base.by_arch[a]["time_mean"])
                       <= rules["weak_time_within"] * base.by_arch[a]["time_mean"]
                       for a, x in s.items())
            if weak:
                r.flags.append("too_weak")
                r.reasons.append("almost no duplicates and mission time within "
                                 f"{100 * rules['weak_time_within']:.0f}% of loss-free - "
                                 "the degradation does not affect coordination")
        if all(x["clean_rate"] >= rules["trivial_success_rate"] for x in s.values()) \
                and r is not base:
            r.flags.append("trivial_success")
            r.reasons.append("every architecture succeeds cleanly in almost every run")
        if all(x["mission_ok_rate"] <= rules["trivial_failure_rate"] for x in s.values()):
            r.flags.append("trivial_failure")
            r.reasons.append("the mission fails in almost every run, for every architecture")
        elif "useless" not in r.flags and all(
                x["clean_rate"] <= rules["trivial_failure_rate"]
                and x["dup_mean"] >= rules["saturated_dup_fraction"] * sectors
                for x in s.values()):
            r.flags.append("trivial_failure")
            r.reasons.append("coordination fails in every run: no clean success and "
                             f"over {100 * rules['saturated_dup_fraction']:.0f}% of sectors "
                             "duplicated for every architecture - no room left to tell "
                             "them apart")
        if rules.get("min_seed_variance") and all(x["flat"] for x in s.values()) \
                and r is not base:
            r.flags.append("flat")
            r.reasons.append("every seed gives the same outcome - repeated seeds add "
                             "no information")
        r.flags = sorted(set(r.flags))
        if r is base:
            r.flags = [f for f in r.flags if f not in ("too_weak", "trivial_success")]
            r.reasons.insert(0, "loss-free reference level")


def select(results: List[LevelResult]) -> Dict[str, Any]:
    """Final levels from the loss axis: nominal, the mildest usable level and
    the harshest usable level."""
    loss = sorted((r for r in results if r.level.axis == "loss"), key=lambda r: r.level.x)
    base = loss[0] if loss else None
    # The usable band is contiguous: from the mildest usable level up to the
    # first level that is rejected. A level that passes again further up (one
    # that is usable at 70% after 60% was not) is noise in ten seeds, not a
    # place where communication starts working again.
    usable, started = [], False
    for r in loss:
        if r.level.x <= 0:
            continue
        if r.usable:
            usable.append(r)
            started = True
        elif started:
            break
    out = {"nominal": base, "moderate": usable[0] if usable else None,
           "severe": usable[-1] if len(usable) > 1 else None,
           "usable_band": [r.level.name for r in usable]}
    return out


def explain(choice, results, coordinating=("C", "D")) -> List[str]:
    """One paragraph per chosen level: why it is meaningful."""
    lines = []
    for role in ("nominal", "moderate", "severe"):
        r = choice.get(role)
        if r is None:
            lines.append(f"- **{role}**: no level qualifies - widen the ladder.")
            continue
        p = r.level.profile
        bits = []
        for a in coordinating:
            x = r.by_arch.get(a)
            if x:
                bits.append(f"{a}: {x['dup_mean']:.1f} ± {x['dup_sd']:.1f} duplicated "
                            f"sectors, {x['time_mean']:.0f} ± {x['time_sd']:.0f} s, "
                            f"clean success {100 * x['clean_rate']:.0f}%")
        b = r.by_arch.get("B")
        ref = (f" B (no coordination) is unaffected by the network, as it should be "
               f"({b['coverage_mean']:.2f} coverage at every level)." if b else "")
        why = {"nominal": "the loss-free reference every other level is compared with.",
               "moderate": "the mildest loss at which coordination visibly suffers: "
                           "duplicates appear and mission time rises, but most runs "
                           "still succeed cleanly.",
               "severe": "the harshest loss at which communication is still worth "
                         "having: enough messages arrive for coordination to change "
                         "the outcome, so architectures can still be told apart."}[role]
        lines.append(f"- **{role} = {p.packet_loss_probability:.0%} loss, "
                     f"{p.latency_ms_mean:.0f} ± {p.latency_ms_jitter:.0f} ms** - {why} "
                     + "; ".join(bits) + "." + ref)
    return lines
