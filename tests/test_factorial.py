"""Phase 18: the main factorial experiment.

Checks the properties a reviewer would ask about before trusting 1,920 runs:

  18.1  common random numbers - one seed, one mission, for every architecture
  18.2  development / validation / test seeds never mix; held-out results seal
        the configuration
  18.3  the principal model is a fixed local one, recorded per run
  18.4  every model decision is saved, attempt by attempt
  exit  exclusions follow the predeclared technical criteria and nothing else;
        every cell is counted against its required replications

Run: python tests/test_factorial.py
"""

import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agentic_uav.coordination import comms_conditions as cc
from agentic_uav.coordination.network_model import NetworkModel, NetworkProfile
from agentic_uav.coordination.protocols import AgentMessage, MessageType
from agentic_uav.experiments import factorial as fx
from agentic_uav.experiments import freeze as fz
from agentic_uav.experiments.experiment_config import ExperimentConfig
from agentic_uav.experiments.experiment_runner import ROOT, run_experiment
from agentic_uav.simulator import scenario_family as sf

PASS, FAIL = [], []
DESIGNS = os.path.join(ROOT, "configs", "experiments")


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append((name, detail))


def _dev_cfg(**kw):
    base = dict(experiment_id="t18", architecture="C", scenario="family:development",
                team_size=4, network_profile="final_nominal", failure_profile="one_failure",
                random_seed=1, planner="scripted", crn=True, fault_interrupts_skill=True)
    base.update(kw)
    return ExperimentConfig(**base)


def _run(out, **kw):
    cfg = _dev_cfg(**kw)
    return cfg, run_experiment(cfg, out_root=out)


# --- 18.1 common random numbers ------------------------------------------------------

def test_one_seed_is_one_mission_for_every_architecture():
    out = tempfile.mkdtemp(prefix="p18_")
    try:
        draws = {}
        for a in ("A", "B", "C", "D"):
            cfg, res = _run(out, experiment_id=f"crn_{a}", architecture=a)
            m = res.manifest
            draws[a] = (json.dumps(m.scenario_draws, sort_keys=True), json.dumps(m.faults))
        check("same targets, zone, batteries and fault for A, B, C and D",
              len(set(draws.values())) == 1, draws)
    finally:
        shutil.rmtree(out, ignore_errors=True)


def test_seeds_differ_and_team_sizes_share():
    a, b = sf.generate("development", 1, 4), sf.generate("development", 2, 4)
    check("different seeds give different missions",
          sf.describe(a)["targets"] != sf.describe(b)["targets"])
    two, four, eight = (sf.generate("development", 5, n) for n in (2, 4, 8))
    d2, d4, d8 = sf.describe(two), sf.describe(four), sf.describe(eight)
    check("2, 4 and 8 drones on one seed share the targets and the zone",
          d2["targets"] == d4["targets"] == d8["targets"]
          and d2["restricted_zone"] == d4["restricted_zone"] == d8["restricted_zone"])
    check("and the batteries of the drones they have in common",
          all(d8["batteries"][v] == d4["batteries"][v] for v in d4["batteries"]))
    check("an 8-drone team searches the same area in 8 sectors",
          len(eight.sectors) == 8 and _area(eight) == _area(four))
    gen = [sf.generate("development", 7, 4) for _ in range(2)]
    check("generation is reproducible", sf.describe(gen[0]) == sf.describe(gen[1]))
    for s in range(1, 30):
        sc = sf.generate("development", s, 4)
        zone = sc.restricted_zones[0].polygon
        for t in sc.targets:
            inside_sector = any(x.footprint.contains(t.position.x, t.position.y)
                                for x in sc.sectors)
            if not inside_sector:
                check("every target lies inside a sector", False, (s, t))
                return
        if _overlaps(zone, sc.sectors) or _inside(zone, 0, 0):
            check("the zone never overlaps a sector or the base", False, (s, zone))
            return
    check("every target lies inside a sector", True)
    check("the zone never overlaps a sector or the base", True)


def _area(sc):
    return sum((s.footprint.max_x - s.footprint.min_x) * (s.footprint.max_y - s.footprint.min_y)
               for s in sc.sectors)


def _inside(poly, x, y):
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    return min(xs) <= x <= max(xs) and min(ys) <= y <= max(ys)


def _overlaps(poly, sectors):
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    for s in sectors:
        f = s.footprint
        if not (max(xs) < f.min_x or min(xs) > f.max_x or max(ys) < f.min_y or min(ys) > f.max_y):
            return True
    return False


def _msg(sender, seq, now):
    return AgentMessage(message_type=MessageType.HEARTBEAT, sender_id=sender,
                        recipient_ids=["Drone2"], timestamp=now, sequence_number=seq,
                        payload={})


def test_per_link_streams_give_equivalent_loss_sequences():
    p = NetworkProfile(name="t", latency_ms_mean=150, latency_ms_jitter=50,
                       packet_loss_probability=0.4)

    def fates(extra_traffic):
        net = NetworkModel(p, seed=42, streams="per_link")
        out = []
        for k in range(200):
            for j in range(extra_traffic):           # other links, varying volume
                net.evaluate(_msg("Drone3", j, k), "Drone3", "Drone4", float(k))
            v = net.evaluate(_msg("Drone1", k, k), "Drone1", "Drone2", float(k))
            out.append((v.delivered, round(v.delay_s, 9)))
        return out
    check("the k-th message on a link meets the same luck whatever else is sent",
          fates(0) == fates(3) == fates(7))

    def shared(extra):
        net = NetworkModel(p, seed=42)
        out = []
        for k in range(200):
            for j in range(extra):
                net.evaluate(_msg("Drone3", j, k), "Drone3", "Drone4", float(k))
            out.append(net.evaluate(_msg("Drone1", k, k), "Drone1", "Drone2", float(k)).delivered)
        return out
    check("(the shared stream does not - which is why 18.1 needs this)",
          shared(0) != shared(3))
    net = NetworkModel(p, seed=1, streams="per_link")
    got = sum(net.evaluate(_msg("Drone1", k, 0), "Drone1", "Drone2", 0.0).delivered
              for k in range(4000)) / 4000
    check("per-link streams keep the configured loss rate", abs(got - 0.6) < 0.03, got)


def test_the_partition_fits_any_team_and_includes_the_controller():
    for n in (2, 4, 8):
        ids = [f"Drone{i + 1}" for i in range(n)]
        part = cc.resolve("final_partitioned", ids).partitions[0]
        drones_a = [v for v in part.group_a if v.startswith("Drone")]
        check(f"{n} drones split into halves", len(drones_a) == n // 2
              and len(part.group_b) == n - n // 2, part)
        check(f"{n} drones: the centralized controller is on the base side",
              "FleetController" in part.group_a)
    out = tempfile.mkdtemp(prefix="p18_")
    try:
        _, nom = _run(out, experiment_id="pa_n", architecture="A", failure_profile="none")
        _, par = _run(out, experiment_id="pa_p", architecture="A", failure_profile="none",
                      network_profile="final_partitioned")
        drops = par.result.raw["bus"].get("drop_reasons", {})
        check("a partition actually cuts drones off from the controller",
              drops.get("partitioned", 0) > 0, drops)
    finally:
        shutil.rmtree(out, ignore_errors=True)


def test_a_failure_inside_a_sweep_costs_the_sweep():
    from agentic_uav.experiments import architectures as arch
    from agentic_uav.simulator.mock_adapter import MockVehicleAdapter
    sc = sf.generate("development", 1, 4)
    fault = sf.fault_of(sc)
    vid, at = next(iter(fault.items()))
    res = {}
    for interrupt in (False, True):
        b = arch.build("B", sc, lambda v: MockVehicleAdapter(0.0), condition="final_nominal",
                       seed=1, heartbeat_interval_s=8.0, crn=True)
        r = arch.run(b, stop_at=fault, interrupt_skills=interrupt)
        agent = next(a for a in b.agents if a.vehicle_id == vid)
        res[interrupt] = (r.coverage, agent.adapter.track[vid][-1][1])
    check("without interruption the dying drone still finishes its sweep",
          res[False][0] == 1.0, res)
    check("with it, the interrupted sweep is not credited", res[True][0] == 0.75, res)
    check("and the track ends at the fault time", abs(res[True][1] - at) < 1e-6, res)


def test_eight_drones_run():
    out = tempfile.mkdtemp(prefix="p18_")
    try:
        cfg, res = _run(out, team_size=8, failure_profile="none")
        check("an 8-drone team completes the mission",
              res.ok and res.result.coverage == 1.0 and len(res.manifest.team) == 8,
              res.summary())
    finally:
        shutil.rmtree(out, ignore_errors=True)


# --- 18.2 splits and the seal ------------------------------------------------------

def test_splits_never_mix():
    dev = sf.seeds_for("development", 50)
    test = sf.seeds_for("test", 20)
    val = fz.validation_seeds()
    check("development, validation and test seeds are disjoint",
          not (set(dev) & set(test)) and not (set(dev) & set(val)) and not (set(test) & set(val)))
    check("test seeds are the stored held-out seeds, in order",
          test == fz.heldout_seeds()[:20])
    for split, seed in (("development", test[0]), ("test", dev[0]), ("development", val[0])):
        try:
            sf.generate(split, seed, 4)
            check(f"a {sf.split_of(seed)} seed is refused for {split}", False)
        except ValueError:
            check(f"a {sf.split_of(seed)} seed is refused for {split}", True)


def test_held_out_results_seal_the_configuration():
    d = tempfile.mkdtemp(prefix="seal_")
    old_seal, old_check = fx.SEAL_PATH, fz.check
    fx.SEAL_PATH = os.path.join(d, "seal.json")
    fz.check = lambda: {"ok": True, "changes": []}
    try:
        design = fx.load_design(os.path.join(DESIGNS, "factorial_main.yaml"))
        excl = fx.load_exclusions()
        fp = {"prompts": "aaa", "task_rules": "bbb"}
        check("a development design needs no seal",
              fx.check_test_split(fx.load_design(os.path.join(DESIGNS, "factorial_dev.yaml")),
                                  fp, excl) is None)
        seal = fx.check_test_split(design, fp, excl)
        check("the first held-out run writes the seal", os.path.exists(fx.SEAL_PATH)
              and seal["fingerprint"] == fp)
        check("an unchanged configuration may continue",
              fx.check_test_split(design, fp, excl)["sealed_at"] == seal["sealed_at"])
        try:
            fx.check_test_split(design, {"prompts": "tuned", "task_rules": "bbb"}, excl)
            check("a prompt tuned after the held-out results is refused", False)
        except RuntimeError as e:
            check("a prompt tuned after the held-out results is refused", "prompts" in str(e))
        try:
            fx.check_test_split(design, fp, dict(excl, _sha256="different"))
            check("changed exclusion criteria are refused", False)
        except RuntimeError:
            check("changed exclusion criteria are refused", True)
        fz.check = lambda: {"ok": False, "changes": ["prompts.x: a -> b"]}
        os.remove(fx.SEAL_PATH)
        try:
            fx.check_test_split(design, fp, excl)
            check("held-out runs need an unchanged freeze", False)
        except RuntimeError:
            check("held-out runs need an unchanged freeze", True)
    finally:
        fx.SEAL_PATH, fz.check = old_seal, old_check
        shutil.rmtree(d, ignore_errors=True)
    check("the repository has not been sealed by a test",
          not os.path.exists(os.path.join(ROOT, "configs", "frozen", "test_seal.json"))
          or json.load(open(os.path.join(ROOT, "configs", "frozen", "test_seal.json")))
          .get("design_id") == "main_v1")


# --- the design --------------------------------------------------------------

def test_the_main_design():
    d = fx.load_design(os.path.join(DESIGNS, "factorial_main.yaml"))
    check("stage 1 is 64 cells x 20 seeds", len(fx.cells(d, "1")) == 64
          and len(fx.expand(d, "1")) == 1280)
    check("with 8 drones, 96 cells and 1,920 runs", len(fx.cells(d, "all")) == 96
          and len(fx.expand(d, "all")) == 1920)
    cfgs = fx.expand(d, "1")
    check("every run uses common random numbers and the held-out split",
          all(c.crn and c.scenario == "family:test" for c in cfgs))
    by_arch = {}
    for c in cfgs:
        by_arch.setdefault(c.architecture_key, set()).add(c.random_seed)
    check("every architecture gets the same seeds", len({frozenset(v) for v in by_arch.values()}) == 1)
    check("18.3: the principal model is a fixed local model",
          d["planner"] == "llama3.1:8b")
    g = fx.load_design(os.path.join(DESIGNS, "factorial_gemini.yaml"))
    check("Gemini is the secondary comparison, on the same split and seeds",
          g["split"] == d["split"] and fx.seeds(g) == fx.seeds(d)
          and str(g["planner"]).startswith("gemini"))


# --- 18.4 every decision is saved --------------------------------------------------

def test_every_model_decision_is_saved():
    out = tempfile.mkdtemp(prefix="p18_")
    try:
        cfg, res = _run(out, architecture="D")
        m = json.load(open(os.path.join(res.directory, "manifest.json")))
        check("a complete agentic run has no transcript gaps",
              fx.transcript_problems(res.directory, m) == [],
              fx.transcript_problems(res.directory, m))
        path = os.path.join(res.directory, "llm", "Drone1.json")
        t = json.load(open(path))
        model_turns = [x for x in t["turns"] if x["exchanges"]]
        check("each model call records its attempts and their validation",
              model_turns and all(ex["validation"] for x in model_turns for ex in x["exchanges"]))
        check("the model card is saved", t["model"].get("model"))
        x = model_turns[0]
        x["raw_response"] = None
        x["exchanges"][0]["raw_response"] = None
        json.dump(t, open(path, "w"))
        check("a decision whose reply was not saved is caught",
              fx.transcript_problems(res.directory, m) != [])
    finally:
        shutil.rmtree(out, ignore_errors=True)


def test_a_correction_is_saved_with_both_attempts():
    from agentic_uav.agents.llm_backends import ScriptedBackend
    from agentic_uav.agents.llm_policy import LLMAgentPolicy
    from agentic_uav.experiments.llm_log import LLMTurn
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    from run_llm_agents import sensible_model
    answers = ["not json at all"]

    def reply(system, user, **kw):
        return answers.pop(0) if answers else sensible_model(system, user, **kw)
    turn = LLMTurn(step=1, time_s=0.0, vehicle_id="Drone1", system_prompt="s", user_prompt="u")
    pol = LLMAgentPolicy(ScriptedBackend(default=reply), "Drone1", timeout_s=None)
    raw, err = pol._ask("s", "u", None, turn)                  # noqa: SLF001
    raw2, err2 = pol._ask("s", "u + correction", None, turn, prompt_for_log="u + correction")  # noqa: SLF001
    check("both attempts are kept, with the correction prompt",
          len(turn.exchanges) == 2 and turn.exchanges[1]["prompt"] == "u + correction"
          and turn.exchanges[0]["raw_response"] == "not json at all", turn.exchanges)


# --- exit criterion: exclusions ---------------------------------------------------------

def test_exclusions_are_technical_only():
    out = tempfile.mkdtemp(prefix="p18_")
    excl = fx.load_exclusions()
    fp = fz.fingerprint(fz.snapshot())
    try:
        cfg, res = _run(out, experiment_id="ex_ok", architecture="B")
        v = fx.classify(res.directory, cfg, excl, fp)
        check("a run with a poor outcome (B loses a sector) is valid",
              v["status"] == "valid" and res.result.coverage < 1.0, (v, res.result.coverage))
        r = json.load(open(os.path.join(res.directory, "result.json")))
        # The log audit does compare the result's sector counts with the event
        # stream - a *consistency* check, so it is left alone here; any outcome
        # value that agrees with its own log is never a reason to exclude.
        r.update(coverage=0.0, mission_time_s=1e9, drones_home=0, targets_found=0,
                 guardian_interventions=500)
        json.dump(r, open(os.path.join(res.directory, "result.json"), "w"))
        check("no outcome, however bad, changes the verdict",
              fx.classify(res.directory, cfg, excl, fp)["status"] == "valid")

        def with_manifest(name, **change):
            c, rr = _run(out, experiment_id=name, architecture="C")
            mp = os.path.join(rr.directory, "manifest.json")
            m = json.load(open(mp))
            m.update(change)
            json.dump(m, open(mp, "w"))
            return c, rr.directory
        c, d = with_manifest("ex_infra", status="failed", error_type="ConnectionRefusedError",
                             error_message="ollama not running")
        v = fx.classify(d, c, excl, fp)
        check("an unreachable model server is an infrastructure exclusion (X1)",
              v["status"] == "excluded" and v["reasons"][0].startswith("X1"), v)
        c, d = with_manifest("ex_sys", status="failed", error_type="ValueError",
                             error_message="bad command")
        v = fx.classify(d, c, excl, fp)
        check("an exception in the system under test is a failed mission, not an exclusion",
              v["status"] == "valid" and v["system_failure"], v)
        c, d = with_manifest("ex_fp", freeze_fingerprint={"prompts": "other"})
        v = fx.classify(d, c, excl, fp)
        check("a run under another configuration is excluded (X3)",
              any(x.startswith("X3") for x in v["reasons"]), v)
        c, rr = _run(out, experiment_id="ex_logs", architecture="C")
        os.remove(os.path.join(rr.directory, "events.jsonl"))
        v = fx.classify(rr.directory, c, excl, fp)
        check("a run with missing logs is excluded (X2)",
              any(x.startswith("X2") for x in v["reasons"]), v)
        c, rr = _run(out, experiment_id="ex_model", architecture="D")
        for name in os.listdir(os.path.join(rr.directory, "llm")):
            p = os.path.join(rr.directory, "llm", name)
            t = json.load(open(p))
            for turn in t["turns"]:
                for ex in turn.get("exchanges", []):
                    ex["transport_error"], ex["raw_response"] = "backend: connection refused", None
            json.dump(t, open(p, "w"))
        v = fx.classify(rr.directory, c, excl, fp)
        check("a model that was never reached is excluded (X4)",
              any(x.startswith("X4") for x in v["reasons"]), v)
    finally:
        shutil.rmtree(out, ignore_errors=True)

    src = open(os.path.join(ROOT, "agentic_uav", "experiments", "factorial.py"),
               encoding="utf-8").read()
    body = src[src.index("def classify("):src.index("def _transport_failure_fraction")]
    check("classify() never reads the result file",
          "result.json" not in body and "coverage" not in body)
    names = [c["id"] for c in excl["criteria"]]
    check("the criteria are the four predeclared technical ones",
          names == ["X1_infrastructure_error", "X2_incomplete_logs",
                    "X3_configuration_mismatch", "X4_model_unreachable"], names)


def test_the_runner_end_to_end_and_resumes():
    import subprocess
    out = tempfile.mkdtemp(prefix="p18_run_")
    try:
        cmd = [sys.executable, os.path.join(ROOT, "scripts", "run_factorial.py"),
               os.path.join(DESIGNS, "factorial_dev.yaml"), "--out", out, "--only", "_n2_final_nominal_"]
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        p1 = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=ROOT)
        p2 = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=ROOT)
        check("the development design runs", "24 run(s) executed" in p1.stdout, p1.stdout[-400:] + p1.stderr[-400:])
        check("a second invocation resumes and runs nothing",
              "0 run(s) executed" in p2.stdout, p2.stdout[-200:])
        for name in ("runs.csv", "cells.csv", "by_network.csv", "by_failure.csv",
                     "report.md", "design_manifest.json"):
            if not os.path.exists(os.path.join(out, name)):
                check(f"the runner writes {name}", False)
                return
        check("the runner writes every summary file", True)
    finally:
        shutil.rmtree(out, ignore_errors=True)


# --- the pre-run review: fixes made before any held-out run ------------------

def _dev_run(key, seed, net, fault=True, n=4):
    from agentic_uav.experiments import architectures as arch
    from agentic_uav.simulator.mock_adapter import MockVehicleAdapter
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    from run_llm_agents import sensible_model
    from agentic_uav.agents.llm_backends import ScriptedBackend
    sc = sf.generate("development", seed, n)
    b = arch.build(key, sc, lambda v: MockVehicleAdapter(0.0), condition=net, seed=seed,
                   backend=ScriptedBackend(default=sensible_model) if key == "D" else None,
                   heartbeat_interval_s=8.0, crn=True)
    r = arch.run(b, stop_at=sf.fault_of(sc) if fault else {}, interrupt_skills=True)
    return b, r


def test_busy_drones_heartbeat_inside_a_sweep():
    b, r = _dev_run("C", 1, "final_nominal", fault=False)
    sweeps = {}
    for e in b.bus.log.entries:
        if e.message_type == "heartbeat":
            sweeps.setdefault(e.sender_id, set()).add(round(e.created_at, 1))
    d1 = sorted(sweeps["Drone1"])
    gaps = [b_ - a for a, b_ in zip(d1, d1[1:])]
    check("a drone heartbeats while it sweeps - no 70 s silence",
          max(gaps) < 20.0, f"largest gap {max(gaps):.1f}s")


def test_a_teammate_that_dies_mid_sweep_is_noticed_in_time():
    # the case that exposed it: D, seed 1, one failure at 63.5 s, nominal comms
    b, r = _dev_run("D", 1, "final_nominal")
    check("its sector is reclaimed and flown", r.coverage == 1.0, r.coverage)
    b, r = _dev_run("C", 1, "final_nominal")
    check("(and by the deterministic agents too)", r.coverage == 1.0, r.coverage)


def test_messages_arrive_on_the_recipients_clock():
    from agentic_uav.coordination.message_bus import MessageBus
    bus = MessageBus(latency_s=0.5)
    a, bb = bus.register("A"), bus.register("B")
    a.send(MessageType.HEARTBEAT, payload={}, recipients=["B"], now=100.0)
    a.receive_available(now=200.0)               # a teammate far ahead reads its mail
    check("a message is not handed over before its delivery time",
          bb.receive_available(now=50.0) == [])
    got = bb.receive_available(now=101.0)
    check("and is handed over once the recipient's clock reaches it", len(got) == 1)
    entry = [e for e in bus.log.entries if e.recipient_id == "B"][0]
    check("its delivery time is the recipient's", abs(entry.actual_delivery_at - 101.0) < 1e-9)
    bus2 = MessageBus(latency_s=0.5)
    x, _y = bus2.register("X"), bus2.register("Y")
    x.send(MessageType.HEARTBEAT, payload={}, recipients=["Y"], now=10.0)
    bus2.flush()
    check("mail to a drone that never reads again still counts as delivered",
          bus2.stats().get("delivered") == 1, bus2.stats())


def test_allocation_waits_for_every_rostered_teammate():
    b, r = _dev_run("C", 2, "final_nominal", fault=False)
    for a in b.agents:
        for t in a.allocator.board.all():
            if t.assigned_agent == a.vehicle_id and t.status.value == "complete":
                heard = set(a.allocator.bids.get(t.task_id, {})) | {a.vehicle_id}
                if len(heard) < 2:
                    check("a claim is made only after rival bids are in", False,
                          (a.vehicle_id, t.task_id, heard))
                    return
    check("a claim is made only after rival bids are in", True)
    # The rule itself, at the moment of claiming. At t = 0 nobody has been
    # heard from, so counting only *heard* teammates let the first drone to
    # step claim with nobody else's bid in.
    from agentic_uav.agents.belief_state import BeliefState
    from agentic_uav.coordination.bidding import Bid
    from agentic_uav.coordination.task_allocator import TaskAllocator
    from agentic_uav.coordination.tasks import MissionTask, TaskBoard, TaskType
    from agentic_uav.core.models import Position3D

    def fresh():
        t = MissionTask("SEARCH_SECTOR_S1", TaskType.SEARCH_SECTOR,
                        required_capabilities={"search"})
        al = TaskAllocator("Drone1", TaskBoard([t]))
        al.roster = ["Drone2", "Drone3"]
        al.bids[t.task_id] = {"Drone1": Bid("Drone1", t.task_id, 0.1)}
        al.bid_opened_at[t.task_id] = 0.0
        b = BeliefState("Drone1", Position3D(0, 0, 0), battery_total_s=900.0)
        return t, al, b
    t, al, b = fresh()
    b.observe(Position3D(0, 0, 0), 1.0)
    check("nobody claims at t = 0 with rostered teammates' bids missing",
          al._claim_best([t], b) is False)                  # noqa: SLF001
    al.bids[t.task_id]["Drone2"] = Bid("Drone2", t.task_id, 0.5)
    al.bids[t.task_id]["Drone3"] = Bid("Drone3", t.task_id, 0.6)
    check("and claims once every rostered teammate has bid", al._claim_best([t], b) is True)  # noqa: SLF001
    t, al, b = fresh()
    al.finished_peers.update({"Drone2", "Drone3"})
    b.observe(Position3D(0, 0, 0), 1.0)
    check("teammates that have landed for good are not waited for",
          al._claim_best([t], b) is True)                   # noqa: SLF001


def test_the_defaults_after_review():
    from agentic_uav.agents import persistent_agent as pa
    check("completion gossip is on everywhere", pa.GOSSIP_COMPLETIONS is True)
    check("standing by for a teammate's unfinished work is on everywhere",
          pa.STAND_BY_FOR_TEAMMATES is True)


def test_the_centralized_controller_recovers_lost_messages():
    # moderate loss, seed 3: the award for S4 was lost and nobody ever flew it
    b, r = _dev_run("A", 3, "final_moderate", fault=False)
    check("a lost award is repeated until the drone holds it", r.coverage == 1.0, r.coverage)
    check("and the fleet lands instead of holding to the step cap",
          not r.hit_step_cap and r.all_landed, (r.hit_step_cap, r.all_landed))
    b, r = _dev_run("A", 1, "final_partitioned", fault=False)
    check("a completion lost to a partition is learned from the drone's status",
          not r.hit_step_cap and r.all_landed, (r.hit_step_cap, r.all_landed))
    hb = sorted(e.created_at for e in b.bus.log.entries
                if e.sender_id == "FleetController" and e.message_type == "heartbeat"
                and e.recipient_id == "Drone1")
    gaps = [y - x for x, y in zip(hb, hb[1:])]
    check("controller heartbeats have no gap longer than an interval",
          max(gaps) <= 15.0 + 1e-6, f"largest gap {max(gaps):.1f}s")


def main():
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        try:
            fn()
        except Exception as e:                                  # noqa: BLE001
            import traceback
            check(f"{fn.__name__} raised", False,
                  f"{type(e).__name__}: {e} {traceback.format_exc()[-300:]}")
    print("Phase 18 factorial experiment\n")
    for n, _ in PASS:
        print(f"  ok    {n}")
    for n, d in FAIL:
        print(f"  FAIL  {n}" + (f"  [{str(d)[:300]}]" if d != "" else ""))
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
