"""Follow-up to main_v1: architecture DV2 (agentic decentralized, task-phase tools).

main_v1's agentic agent (D) re-flew sectors it had already searched: its tool
set had no way to say "this task is done" except `report_target`, and nothing
stopped `start_search` on a finished sector. DV2 is D with exactly that gap
closed - one extra tool, phase-aware validation - and nothing else changed.

The models here are scripted, so the tests are deterministic:

  repeater   always `start_search`   - main_v1's dominant failure (98.5% of D's choices)
  bidder     always `send_bid`       - the choice behind main_v1's 4.7 s airborne exits
  sensible   the scripted control    - must still behave like the deterministic agents

Run: python tests/test_dv2.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agentic_uav.agents import llm_tools
from agentic_uav.agents.decision_schema import DecisionError, parse_decision
from agentic_uav.agents.llm_backends import ScriptedBackend
from agentic_uav.experiments import architectures as arch
from agentic_uav.experiments import factorial as fx
from agentic_uav.experiments.experiment_runner import ROOT
from agentic_uav.simulator import scenario_family as sf
from agentic_uav.simulator.mock_adapter import MockVehicleAdapter

PASS, FAIL = [], []
DESIGNS = os.path.join(ROOT, "configs", "experiments")


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append((name, detail))


def _always(tool, params=None):
    def model(system, user, **kw):
        return json.dumps({
            "situation_assessment": {"mission_progress": "partial",
                                     "communication_status": "nominal",
                                     "current_risk": "low"},
            "selected_tool": tool, "parameters": params or {},
            "confidence": 0.0, "outgoing_messages": []})
    return model


REPEATER = _always("start_search")
BIDDER = _always("send_bid", {"task_id": "SEARCH_SECTOR_S1"})
REPORTER = _always("report_task_complete")


def _fly(key, model, n=2, seed=1, net="final_nominal", fault=False):
    sc = sf.generate("development", seed, n)
    b = arch.build(key, sc, lambda v: MockVehicleAdapter(0.0), condition=net, seed=seed,
                   backend=ScriptedBackend(default=model), heartbeat_interval_s=8.0,
                   crn=True)
    r = arch.run(b, stop_at=sf.fault_of(sc) if fault else {}, interrupt_skills=True)
    return b, r


def _turns(b):
    out = []
    for a in b.agents:
        log = getattr(a.policy, "log", None)
        out.extend(getattr(log, "turns", []) or [])
    return out


# --- the tool set -----------------------------------------------------------------

def test_the_tool_sets():
    v1, v2 = llm_tools.tool_names("v1"), llm_tools.tool_names("v2")
    check("v1 (D, as frozen for main_v1) has no completion tool",
          "report_task_complete" not in v1)
    check("v2 adds exactly one tool", set(v2) - set(v1) == {"report_task_complete"})
    check("the catalogue a v1 agent sees does not mention it",
          "report_task_complete" not in llm_tools.catalogue(toolset="v1"))
    check("the catalogue a v2 agent sees does",
          "report_task_complete" in llm_tools.catalogue(toolset="v2"))
    raw = _always("report_task_complete")("", "")
    try:
        parse_decision(raw, toolset="v1")
        check("a v1 agent cannot use the v2 tool", False)
    except DecisionError:
        check("a v1 agent cannot use the v2 tool", True)
    check("a v2 agent can", parse_decision(raw, toolset="v2").tool_name
          == "report_task_complete")
    check("D is unchanged, DV2 differs from D only in its tool set",
          arch.spec("D").toolset == "v1" and arch.spec("DV2").toolset == "v2"
          and {k for k in vars(arch.spec("D")) if getattr(arch.spec("D"), k)
               != getattr(arch.spec("DV2"), k)} <= {"key", "name", "description",
                                                   "toolset"})


# --- the failure main_v1 measured ----------------------------------------------------

def test_a_model_that_only_searches():
    b, r = _fly("D", REPEATER)
    check("D reproduces main_v1: a 2-drone team does not finish",
          r.coverage < 1.0 or r.mission_time_s > 600, (r.coverage, r.mission_time_s))
    b, r = _fly("DV2", REPEATER)
    check("DV2: the same model's team searches everything", r.coverage == 1.0, r.coverage)
    check("DV2: in about the time the deterministic agents take",
          r.mission_time_s < 400, r.mission_time_s)
    check("DV2: and lands", r.all_landed)
    reasons = [str(getattr(t, "rejection_reason", "")) for t in _turns(b)]
    check("each re-search of a finished sector is recorded as wrong_phase",
          any("wrong_phase" in x for x in reasons), set(reasons))
    b4, r4 = _fly("DV2", REPEATER, n=4)
    check("DV2, 4 drones: complete and landed", r4.coverage == 1.0 and r4.all_landed,
          (r4.coverage, r4.all_landed))


def test_a_model_that_only_bids():
    b, r = _fly("DV2", BIDDER)
    check("DV2: a model that only bids still gets the mission done",
          r.coverage == 1.0, r.coverage)
    check("DV2: no drone is left in the air", r.all_landed)
    check("no airborne exit at a few seconds (main_v1's 4.7 s runs)",
          r.mission_time_s > 60, r.mission_time_s)


def _reports_when_idle(system, user, **kw):
    """The control, except that with no task held it chooses
    report_task_complete - what llama did in the first development run."""
    from run_llm_agents import sensible_model
    ctx = json.loads(user.split("\n\nAvailable tools:")[0])
    if (ctx.get("role_and_task") or {}).get("task") is None:
        return REPORTER(system, user)
    return sensible_model(system, user)


def test_a_model_that_reports_with_nothing_to_report():
    """dv2_dev (llama), 2 of 16 runs: after its report, a drone kept choosing
    report_task_complete with no task held. A report takes no flight time, so it
    looped at one instant until its step budget ran out, airborne. This model
    reproduces both runs (n2 severe seed 1 ended at 317 s, as llama's did)."""
    for n, net, fault in ((2, "final_severe", False), (4, "final_nominal", True)):
        b, r = _fly("DV2", _reports_when_idle, n=n, net=net, fault=fault)
        check(f"{n} drones, {net}: the mission completes", r.coverage == 1.0, r.coverage)
        check(f"{n} drones, {net}: every drone lands", r.all_landed)
        check(f"{n} drones, {net}: no drone burns its step budget at one instant",
              max(len(a.policy.log.turns) for a in b.agents) < 60,
              max(len(a.policy.log.turns) for a in b.agents))
        reasons = {str(getattr(t, "rejection_reason", "")) for t in _turns(b)}
        check(f"{n} drones, {net}: the empty report is rejected as wrong_phase",
              "wrong_phase" in reasons, reasons)


def test_the_scripted_control_still_matches_the_deterministic_agents():
    from run_llm_agents import sensible_model
    for n in (2, 4):
        b, r = _fly("DV2", sensible_model, n=n, fault=True)
        bc, rc = _fly("C", None, n=n, fault=True)
        check(f"DV2 control, {n} drones: complete like C",
              r.coverage == rc.coverage == 1.0, (r.coverage, rc.coverage))
        tools = {getattr(t, "tool", None) for t in _turns(b)}
        check(f"DV2 control, {n} drones: completion is reported with the new tool",
              "report_task_complete" in tools, tools)


def test_dv2_runs_are_audited_like_d_runs():
    import shutil
    import tempfile
    from agentic_uav.experiments.experiment_config import ExperimentConfig
    from agentic_uav.experiments.experiment_runner import run_experiment
    from agentic_uav.experiments import pilot
    check("DV2 counts as agentic for the exclusion and transcript rules",
          fx._is_agentic("DV2") and fx._is_agentic("D") and not fx._is_agentic("C"))
    out = tempfile.mkdtemp(prefix="dv2_")
    try:
        cfg = ExperimentConfig(experiment_id="dv2run", architecture="agentic_decentralized_v2",
                               scenario="family:development", team_size=2,
                               network_profile="final_nominal", failure_profile="none",
                               random_seed=1, planner="scripted", crn=True,
                               fault_interrupts_skill=True)
        res = run_experiment(cfg, out_root=out)
        d = os.path.join(out, "dv2run")
        m = json.load(open(os.path.join(d, "manifest.json"), encoding="utf-8"))
        check("the alias resolves to DV2", m.get("architecture_key") == "DV2",
              m.get("architecture_key"))
        check("its transcripts are saved and complete",
              os.path.isdir(os.path.join(d, "llm"))
              and fx.transcript_problems(d, m) == [], fx.transcript_problems(d, m))
        m2 = dict(m, architecture_key="DV2")
        shutil.rmtree(os.path.join(d, "llm"))
        check("a DV2 run with its transcripts missing is caught",
              fx.transcript_problems(d, m2) != [])
    finally:
        shutil.rmtree(out, ignore_errors=True)


# --- main_v2 -------------------------------------------------------------------------

def test_main_v2_uses_fresh_held_out_seeds():
    v1 = fx.load_design(os.path.join(DESIGNS, "factorial_main.yaml"))
    v2 = fx.load_design(os.path.join(DESIGNS, "factorial_main_v2.yaml"))
    held = sf.seeds_for("test", 100)
    check("main_v1 used held-out seeds 1-20", fx.seeds(v1) == held[:20])
    check("main_v2 uses held-out seeds 21-40", fx.seeds(v2) == held[20:40])
    check("no seed is shared", not set(fx.seeds(v1)) & set(fx.seeds(v2)))
    check("main_v2 compares DV2 with A, B and C on the same cells",
          sorted(fx.load_design(os.path.join(DESIGNS, "factorial_main_v2.yaml"))
                 ["architectures"]) == sorted(["centralized", "independent",
                                               "deterministic_decentralized",
                                               "agentic_decentralized_v2"]))
    check("stage 1 is 64 cells x 20 seeds", len(fx.expand(v2, "1")) == 1280)
    check("each design has its own seal", fx.seal_path("main_v1") != fx.seal_path("main_v2"))


def test_a_design_cannot_reuse_another_designs_seeds():
    import shutil
    import tempfile
    from agentic_uav.experiments import freeze as fz
    d = tempfile.mkdtemp(prefix="seal2_")
    old_seal, old_check = fx.SEAL_PATH, fz.check
    fx.SEAL_PATH = os.path.join(d, "test_seal.json")
    fz.check = lambda: {"ok": True, "changes": []}
    try:
        excl = fx.load_exclusions()
        fp = {"prompts": "a", "task_rules": "b"}
        v1 = fx.load_design(os.path.join(DESIGNS, "factorial_main.yaml"))
        v2 = fx.load_design(os.path.join(DESIGNS, "factorial_main_v2.yaml"))
        fx.check_test_split(v1, fp, excl)
        check("a follow-up on fresh seeds may run after main_v1 is sealed",
              fx.check_test_split(v2, {"prompts": "changed", "task_rules": "b"}, excl)
              is not None)
        clash = dict(v2, design_id="main_v3", seed_plan=dict(v2["seed_plan"], skip=10))
        try:
            fx.check_test_split(clash, fp, excl)
            check("a design overlapping a sealed design's seeds is refused", False)
        except RuntimeError as e:
            check("a design overlapping a sealed design's seeds is refused",
                  "already used" in str(e))
        # a seal written before seeds were stored (the real main_v1 seal)
        with open(fx.SEAL_PATH, encoding="utf-8") as f:
            s = json.load(f)
        s.pop("seeds", None)
        with open(fx.SEAL_PATH, "w", encoding="utf-8") as f:
            json.dump(s, f)
        try:
            fx.check_test_split(dict(v2, design_id="main_v4",
                                     seed_plan=dict(v2["seed_plan"], skip=0)), fp, excl)
            check("an old seal without a seed list still protects its seeds", False)
        except RuntimeError:
            check("an old seal without a seed list still protects its seeds", True)
    finally:
        fx.SEAL_PATH, fz.check = old_seal, old_check
        shutil.rmtree(d, ignore_errors=True)


def main():
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        try:
            fn()
        except Exception as e:                                  # noqa: BLE001
            import traceback
            check(f"{fn.__name__} raised", False,
                  f"{type(e).__name__}: {e} {traceback.format_exc()[-400:]}")
    print("DV2 follow-up (task-phase tools)\n")
    for n, _ in PASS:
        print(f"  ok    {n}")
    for n, d in FAIL:
        print(f"  FAIL  {n}" + (f"  [{str(d)[:300]}]" if d != "" else ""))
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
