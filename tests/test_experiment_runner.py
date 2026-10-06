"""Phase 14: experiments run unattended and record everything.

The tests that matter here are about *evidence*, not behaviour. An experiment
runner that loses a crashed run, or writes an event stream missing half the
mission, produces results nobody can check later - and does so silently, because
every run still appears to succeed.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agentic_uav.experiments.events import (
    EventLog, EventType, read_events)
from agentic_uav.experiments.experiment_config import (
    ARCHITECTURE_ALIASES, FAILURE_PROFILES, ExperimentConfig, Manifest,
    git_sha, software_versions)
from agentic_uav.experiments.experiment_runner import ROOT, run_experiment

CONFIGS = os.path.join(ROOT, "configs", "experiments")


def _tmp():
    return tempfile.mkdtemp(prefix="phase14_")


def _cfg(**kw):
    base = {"experiment_id": "t_run", "architecture": "C",
            "scenario": "search_relay_001", "network_profile": "nominal",
            "random_seed": 7, "planner": "scripted", "max_steps": 400}
    base.update(kw)
    return ExperimentConfig.from_dict(base)


def _run(**kw):
    out = _tmp()
    return run_experiment(_cfg(**kw), out_root=out, root=ROOT), out


# --- 14.1 configuration --------------------------------------------------


def test_the_reference_configuration_loads():
    """The exact file from 14.1 must load and resolve."""
    cfg = ExperimentConfig.load(os.path.join(CONFIGS, "exp_0042.yaml"))
    assert cfg.experiment_id == "exp_0042"
    assert cfg.architecture_key == "D"
    assert cfg.network_profile == "severe"
    assert cfg.random_seed == 42
    assert cfg.faults, "the failure profile resolved to no faults"


def test_long_architecture_names_resolve_to_keys():
    for name, key in ARCHITECTURE_ALIASES.items():
        assert _cfg(architecture=name).architecture_key == key
    assert _cfg(architecture="D").architecture_key == "D"


def test_an_unknown_configuration_key_is_refused():
    """A silently ignored key is a config that does not do what it says."""
    try:
        ExperimentConfig.from_dict({"experiment_id": "x", "temperature": 0.7})
        raise AssertionError("an unknown key was accepted")
    except KeyError as e:
        assert "temperature" in str(e)


def test_an_unknown_failure_profile_is_refused():
    try:
        _cfg(failure_profile="made_up").faults
        raise AssertionError("an unknown failure profile was accepted")
    except KeyError as e:
        assert "made_up" in str(e)


def test_a_batch_file_expands_to_several_configs():
    configs = ExperimentConfig.load_many(
        os.path.join(CONFIGS, "sweep_architectures.yaml"))
    assert len(configs) == 5
    assert {c.architecture_key for c in configs} == set("ABCDE")
    assert len({c.experiment_id for c in configs}) == 5, "ids collide"


def test_every_failure_profile_names_real_vehicles():
    from agentic_uav.simulator.scenario_manager import load_scenario
    sc = load_scenario(os.path.join(ROOT, "configs/missions/search_relay_001.yaml"))
    known = {v.vehicle_id for v in sc.vehicles}
    for name, faults in FAILURE_PROFILES.items():
        unknown = set(faults) - known
        assert not unknown, f"profile {name} kills non-existent {unknown}"


# --- 14.2 manifest -------------------------------------------------------


def test_the_manifest_records_everything_142_asks_for():
    outcome, out = _run()
    try:
        m = json.load(open(os.path.join(outcome.directory, "manifest.json")))
        for required in ("git_sha", "architecture", "scenario", "random_seed",
                         "model", "started_at", "finished_at", "software",
                         "completed", "status", "config"):
            assert required in m, f"the manifest is missing {required}"
        assert m["completed"] is True
        assert m["status"] == "completed"
        assert m["software"]["python"]
        assert m["config"]["random_seed"] == 7
    finally:
        shutil.rmtree(out, ignore_errors=True)


def test_the_git_sha_is_recorded_or_explicitly_unknown():
    sha = git_sha(ROOT)
    assert sha == "unknown" or len(sha.split("-")[0]) >= 7, \
        f"unusable git sha: {sha!r}"


def test_software_versions_distinguish_present_from_absent():
    v = software_versions()
    assert v["python"]
    assert all(isinstance(x, str) for x in v.values())


def test_the_config_is_copied_into_the_result_directory():
    """A result nobody can trace back to a configuration is not reproducible."""
    cfg = ExperimentConfig.load(os.path.join(CONFIGS, "exp_0042.yaml"))
    out = _tmp()
    try:
        r = run_experiment(cfg, out_root=out, root=ROOT)
        copied = os.path.join(r.directory, "config.yaml")
        assert os.path.isfile(copied)
        assert "experiment_id: exp_0042" in open(copied).read()
    finally:
        shutil.rmtree(out, ignore_errors=True)


def test_a_mismatched_team_size_warns_rather_than_silently_differing():
    outcome, out = _run(team_size=9)
    try:
        assert any("team_size" in w for w in outcome.manifest.warnings), \
            "a config asking for 9 drones ran 4 without saying so"
    finally:
        shutil.rmtree(out, ignore_errors=True)


# --- 14.3 structured event log -------------------------------------------


def test_all_nineteen_event_types_are_defined():
    required = {
        "MISSION_STARTED", "OBSERVATION_RECEIVED", "BELIEF_UPDATED",
        "MESSAGE_SENT", "MESSAGE_DROPPED", "MESSAGE_RECEIVED",
        "TASK_ANNOUNCED", "TASK_BID", "TASK_ASSIGNED", "TASK_RELEASED",
        "ROLE_CHANGED", "LLM_CALLED", "DECISION_PROPOSED",
        "GUARDIAN_INTERVENED", "SKILL_STARTED", "SKILL_COMPLETED",
        "TARGET_FOUND", "FAULT_INJECTED", "MISSION_COMPLETED"}
    have = {t.value for t in EventType}
    assert required <= have, f"missing event types: {required - have}"
    assert have == required, f"undeclared extra types: {have - required}"


def test_the_event_stream_is_valid_jsonl_and_time_ordered():
    outcome, out = _run()
    try:
        path = os.path.join(outcome.directory, "events.jsonl")
        events = read_events(path)            # raises if any line is bad JSON
        assert len(events) > 50, f"only {len(events)} events for a whole mission"
        times = [e["t"] for e in events]
        assert times == sorted(times), "the stream is not in simulated-time order"
        seqs = [e["seq"] for e in events]
        assert seqs == list(range(1, len(seqs) + 1)), "sequence numbers are not dense"
    finally:
        shutil.rmtree(out, ignore_errors=True)


def test_every_event_declares_whether_it_was_live_or_derived():
    """Derived events are legitimate; pretending they were captured live is not."""
    outcome, out = _run()
    try:
        events = read_events(os.path.join(outcome.directory, "events.jsonl"))
        for e in events:
            assert e["source"] == "live" or e["source"].startswith("derived:"), \
                f"event {e['type']} has an unclear source {e['source']!r}"
        assert any(e["source"] == "live" for e in events)
        assert any(e["source"].startswith("derived:") for e in events)
    finally:
        shutil.rmtree(out, ignore_errors=True)


def test_a_full_run_produces_the_lifecycle_and_mission_events():
    outcome, out = _run(failure_profile="drone_failure_early")
    try:
        events = read_events(os.path.join(outcome.directory, "events.jsonl"))
        types = {e["type"] for e in events}
        for required in ("MISSION_STARTED", "MISSION_COMPLETED",
                         "FAULT_INJECTED", "OBSERVATION_RECEIVED",
                         "BELIEF_UPDATED", "DECISION_PROPOSED",
                         "SKILL_STARTED", "SKILL_COMPLETED",
                         "MESSAGE_SENT", "MESSAGE_RECEIVED"):
            assert required in types, f"no {required} in a complete run"
    finally:
        shutil.rmtree(out, ignore_errors=True)


def test_message_events_match_the_bus_log_exactly():
    """The derived stream must not invent or lose messages."""
    from agentic_uav.experiments import architectures as arch
    from agentic_uav.experiments.events import EventLog, derive
    from agentic_uav.simulator.mock_adapter import MockVehicleAdapter
    from agentic_uav.simulator.scenario_manager import load_scenario

    sc = load_scenario(os.path.join(ROOT, "configs/missions/search_relay_001.yaml"))
    built = arch.build("C", sc, lambda v: MockVehicleAdapter(0.0),
                       condition="moderate", seed=3, heartbeat_interval_s=8.0)
    arch.run(built)

    log = derive(EventLog(), built)
    entries = built.bus.log.entries
    sent = sum(1 for e in log.events if e.type == "MESSAGE_SENT")
    dropped = sum(1 for e in log.events if e.type == "MESSAGE_DROPPED")
    received = sum(1 for e in log.events if e.type == "MESSAGE_RECEIVED")

    assert sent == len(entries), \
        f"{sent} MESSAGE_SENT events for {len(entries)} bus entries"
    assert dropped == sum(1 for e in entries if e.dropped)
    assert received == sum(1 for e in entries if e.delivered and not e.dropped)


def test_guardian_interventions_appear_in_the_stream():
    """Only interventions, not every approved command."""
    from agentic_uav.experiments import architectures as arch
    from agentic_uav.experiments.events import EventLog, derive
    from agentic_uav.simulator.mock_adapter import MockVehicleAdapter
    from agentic_uav.simulator.scenario_manager import load_scenario

    sc = load_scenario(os.path.join(ROOT, "configs/missions/search_relay_001.yaml"))
    built = arch.build("C", sc, lambda v: MockVehicleAdapter(0.0),
                       condition="severe", seed=17, heartbeat_interval_s=8.0)
    arch.run(built)
    log = derive(EventLog(), built)

    events = [e for e in log.events if e.type == "GUARDIAN_INTERVENED"]
    actual = sum(len(a.guardian_log.interventions()) for a in built.agents)
    assert len(events) == actual, \
        f"{len(events)} guardian events for {actual} interventions"
    for e in events:
        assert e.data.get("outcome") != "approve", \
            "an approved command was logged as an intervention"


def test_absent_event_types_are_reported_not_hidden():
    log = EventLog()
    log.emit(EventType.MISSION_STARTED)
    missing = log.missing_types()
    assert "LLM_CALLED" in missing and "GUARDIAN_INTERVENED" in missing
    assert "MISSION_STARTED" not in missing


def test_an_llm_run_records_llm_calls_and_saves_transcripts():
    outcome, out = _run(architecture="agentic_decentralized",
                        experiment_id="t_llm")
    try:
        events = read_events(os.path.join(outcome.directory, "events.jsonl"))
        calls = [e for e in events if e["type"] == "LLM_CALLED"]
        assert calls, "an agentic run recorded no LLM calls"
        assert any("tool" in e["data"] for e in calls)
        llm_dir = os.path.join(outcome.directory, "llm")
        assert os.path.isdir(llm_dir) and os.listdir(llm_dir), \
            "no prompt/response transcripts were saved"
    finally:
        shutil.rmtree(out, ignore_errors=True)


# --- 14.4 failed runs are preserved --------------------------------------


def test_a_crashed_run_still_produces_a_complete_result_directory():
    """The core requirement of 14.4, and the easiest thing to get wrong."""
    cfg = ExperimentConfig.load(os.path.join(CONFIGS, "_broken_example.yaml"))
    out = _tmp()
    try:
        outcome = run_experiment(cfg, out_root=out, root=ROOT)
        assert not outcome.ok, "the deliberately broken config did not fail"
        for required in ("manifest.json", "events.jsonl", "error.txt",
                         "config.yaml"):
            path = os.path.join(outcome.directory, required)
            assert os.path.isfile(path), f"a failed run lost {required}"

        m = json.load(open(os.path.join(outcome.directory, "manifest.json")))
        assert m["completed"] is False
        assert m["status"] == "failed"
        assert m["error_type"] and m["error_message"]
        assert m["traceback"], "no traceback recorded"
        assert m["git_sha"], "a failed run still needs its commit recorded"

        events = read_events(os.path.join(outcome.directory, "events.jsonl"))
        assert events, "a failed run lost its event stream"
    finally:
        shutil.rmtree(out, ignore_errors=True)


def test_a_failure_part_way_through_keeps_the_events_up_to_that_point():
    """A crash mid-mission must not take the evidence with it."""
    from agentic_uav.agents.persistent_agent import PersistentAgent
    original = PersistentAgent.step
    calls = {"n": 0}

    def exploding(self):
        calls["n"] += 1
        if calls["n"] > 12:
            raise RuntimeError("injected mid-mission failure")
        return original(self)

    out = _tmp()
    PersistentAgent.step = exploding
    try:
        outcome = run_experiment(_cfg(experiment_id="t_crash"),
                                 out_root=out, root=ROOT)
        assert not outcome.ok
        events = read_events(os.path.join(outcome.directory, "events.jsonl"))
        types = {e["type"] for e in events}
        assert "MISSION_STARTED" in types
        assert len(events) > 10, \
            f"only {len(events)} events survived a mid-mission crash"
        assert outcome.manifest.error_type == "RuntimeError"
    finally:
        PersistentAgent.step = original
        shutil.rmtree(out, ignore_errors=True)


# --- the exit criterion --------------------------------------------------


def test_a_batch_runs_a_list_of_configs_without_prompts():
    """One command, several configs, one complete directory per run."""
    out = _tmp()
    try:
        proc = subprocess.run(
            [sys.executable, os.path.join(ROOT, "scripts", "run_batch.py"),
             os.path.join(CONFIGS, "sweep_architectures.yaml"),
             "--out", out],
            capture_output=True, text=True, timeout=900, stdin=subprocess.DEVNULL)
        assert proc.returncode == 0, \
            f"the batch reported failures:\n{proc.stdout[-1500:]}"

        configs = ExperimentConfig.load_many(
            os.path.join(CONFIGS, "sweep_architectures.yaml"))
        for cfg in configs:
            d = os.path.join(out, cfg.experiment_id)
            assert os.path.isdir(d), f"no result directory for {cfg.experiment_id}"
            for required in ("manifest.json", "events.jsonl", "result.json"):
                assert os.path.isfile(os.path.join(d, required)), \
                    f"{cfg.experiment_id} is missing {required}"

        index = json.load(open(os.path.join(out, "index.json")))
        assert index["runs"] == len(configs)
        assert all(r["completed"] for r in index["rows"])
        assert os.path.isfile(os.path.join(out, "index.csv"))
    finally:
        shutil.rmtree(out, ignore_errors=True)


def test_a_batch_continues_past_a_failed_run_and_reports_it():
    out = _tmp()
    try:
        proc = subprocess.run(
            [sys.executable, os.path.join(ROOT, "scripts", "run_batch.py"),
             os.path.join(CONFIGS, "_broken_example.yaml"),
             os.path.join(CONFIGS, "exp_0042.yaml"),
             "--out", out],
            capture_output=True, text=True, timeout=900, stdin=subprocess.DEVNULL)
        # a batch with a failure exits non-zero, but still runs everything
        assert proc.returncode == 1, "a failed run did not affect the exit code"
        assert os.path.isdir(os.path.join(out, "exp_0042")), \
            "the batch stopped at the first failure instead of continuing"
        assert os.path.isdir(os.path.join(out, "exp_broken"))
        index = json.load(open(os.path.join(out, "index.json")))
        assert index["runs"] == 2
        assert sum(1 for r in index["rows"] if not r["completed"]) == 1
    finally:
        shutil.rmtree(out, ignore_errors=True)


def test_repeat_varies_only_the_seed():
    from run_batch import expand
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    base = _cfg(random_seed=10)
    out = expand([base], repeat=3)
    assert len(out) == 3
    assert [c.random_seed for c in out] == [10, 11, 12]
    assert len({c.experiment_id for c in out}) == 3
    for c in out:
        assert c.architecture == base.architecture
        assert c.network_profile == base.network_profile


def test_the_same_configuration_reproduces_the_same_result():
    a, out_a = _run(experiment_id="t_repro_a", network_profile="severe")
    b, out_b = _run(experiment_id="t_repro_b", network_profile="severe")
    try:
        assert a.ok and b.ok
        assert (a.result.coverage, a.result.messages_sent,
                a.result.duplicated_sectors) == \
               (b.result.coverage, b.result.messages_sent,
                b.result.duplicated_sectors), \
            "the same configuration produced different results"
    finally:
        shutil.rmtree(out_a, ignore_errors=True)
        shutil.rmtree(out_b, ignore_errors=True)


if __name__ == "__main__":
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    passed = failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ok    {name[5:].replace('_', ' ')}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {name[5:].replace('_', ' ')}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
