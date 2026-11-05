#!/usr/bin/env python3
"""Tests for Phase 12's exit: each check shown able to fail, on a real flight's record altered to break it.

    python -m unittest discover -s tests -p test_llm_exit.py

WHY THESE EXIST
---------------
The exit says each drone decided with its own context, that the model really
decided, that nothing reached a skill unreviewed, and that every flight replays
exactly from its record. These fly one seed with the echo model -- the exit's
own machinery, no server -- and then plant each failure: a context given to the
wrong drone, a teammate entry holding more than was said, a memory that is not
the drone's own, a drone that never asked its model, a fallback with no reason,
a command at the handle unreviewed, a skill started by no decision, a replay that
differs. Each check must say so.
"""

import copy
import dataclasses
import io
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agentic_uav.coordination.keepout import KeepOutConfig  # noqa: E402
from agentic_uav.experiments import llm_exit as X  # noqa: E402
from agentic_uav.experiments.allocation import load_allocation  # noqa: E402
from agentic_uav.experiments.guardian_exit import load_guardian  # noqa: E402
from agentic_uav.experiments.recovery import load_recovery  # noqa: E402
from agentic_uav.experiments.scenarios import load_scenario  # noqa: E402
from agentic_uav.planners.llm_ask import EchoAsk  # noqa: E402

FLY = {"guardian": load_guardian(), "keep_out": KeepOutConfig(5.0, 10.0, 3.0)}


class ExitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.flights = X.llm_flights(load_scenario("search_relay_001"), 17, load_allocation(), load_recovery(),
                                    EchoAsk(), FLY)

    def checked(self, label, **change):
        flights = dict(self.flights, **{label: dict(self.flights[label], **change)})
        return X.exit_checks(flights)

    def test_all_hold_with_the_echo(self):
        c = X.exit_checks(self.flights)
        self.assertTrue(c["all"], {k: v["problems"] for k, v in c.items() if k != "all"})
        f = X.findings(self.flights)
        self.assertEqual(sorted(f), ["Drone1 stopped", "no stop"])
        self.assertTrue(all(x["met"] and x["model_decisions"] == x["agreed"] > 50 for x in f.values()))

    def logs_with(self, label, fn):
        logs = copy.deepcopy(self.flights[label]["logs"])
        fn(logs)
        return logs

    def first_model(self, logs, drone="Drone2"):
        return next(e for e in logs[drone]["log"] if e["kind"] != "procedural")

    def test_a_context_given_to_the_wrong_drone(self):
        logs = self.logs_with("no stop", lambda l: self.first_model(l)["context"]["you"].update(id="Drone3"))
        self.assertIn("was given Drone3's context", self.checked("no stop", logs=logs)["distinct_contexts"]["problems"][0])

    def test_a_teammate_entry_holding_more_than_was_said(self):
        logs = self.logs_with("no stop", lambda l: self.first_model(l)["context"]["teammates"][0].update(stage="x"))
        self.assertFalse(self.checked("no stop", logs=logs)["distinct_contexts"]["ok"])

    def test_a_memory_not_its_own(self):
        def plant(l):
            later = [e for e in l["Drone2"]["log"] if e["kind"] != "procedural"][3]
            later["context"]["memory"] = [{"tool": "return_home", "parameters": {}}]
        logs = self.logs_with("no stop", plant)
        self.assertIn("memory is not its own", self.checked("no stop", logs=logs)["distinct_contexts"]["problems"][0])

    def test_a_drone_that_never_asked_its_model(self):
        def plant(l):
            l["Drone3"]["decisions"] = {"procedural": 5, "fallback": 7}
        logs = self.logs_with("no stop", plant)
        self.assertIn("Drone3 made no decision", self.checked("no stop", logs=logs)["llm_decides"]["problems"][0])

    def test_a_fallback_with_no_reason(self):
        def plant(l):
            e = self.first_model(l)
            e["kind"], e["problems"] = "fallback", []
        logs = self.logs_with("no stop", plant)
        self.assertIn("no reason", self.checked("no stop", logs=logs)["llm_decides"]["problems"][0])

    def test_a_command_unreviewed_or_a_skill_no_decision_started(self):
        run = self.flights["no stop"]["run"]
        guardians = copy.deepcopy(run.guardians)
        guardians["Drone1"]["log"].append({"drone": "Drone1", "at": 1.0, "source": "direct", "outcome": "x",
                                           "checks": [], "reasons": []})
        executed = copy.deepcopy(run.executed)
        executed["Drone2"].append(dict(executed["Drone2"][0], serial=99))
        bad = dataclasses.replace(run, guardians=guardians, executed=executed)
        problems = self.checked("no stop", run=bad)["guarded"]["problems"]
        self.assertTrue(any("unreviewed" in p for p in problems) and any("by approved decisions" in p for p in problems))

    def test_a_replay_that_differs(self):
        run = self.flights["Drone1 stopped"]["run"]
        policies = copy.deepcopy(run.policies)
        policies["Drone2"]["x"] = 1
        c = self.checked("Drone1 stopped", replay=dataclasses.replace(run, policies=policies))
        self.assertFalse(c["replays_exactly"]["ok"])
        self.assertFalse(c["all"])


class ScriptTests(unittest.TestCase):
    def test_a_dry_run_is_never_of_record(self):
        sys.path.insert(0, os.path.join(ROOT, "scripts"))
        import llm_exit as script
        out = tempfile.mkdtemp()
        try:
            with redirect_stdout(io.StringIO()) as buf:
                code = script.main(["--echo", "--seeds", "17", "--out", out, "--block", "t"])
            self.assertEqual(code, 0)
            self.assertIn("**Exit criterion: DRY RUN**", buf.getvalue())
            (jsonl,) = [n for n in os.listdir(out) if n.endswith(".jsonl")]
            import json
            with open(os.path.join(out, jsonl), encoding="utf-8") as h:
                header = json.loads(h.readline())
            self.assertEqual((header["dry_run"], header["exit_criterion_met"], header["model"]), (True, False, "echo"))
        finally:
            shutil.rmtree(out, ignore_errors=True)

    def test_it_needs_a_server_or_the_echo_not_both(self):
        sys.path.insert(0, os.path.join(ROOT, "scripts"))
        import llm_exit as script
        for argv in ([], ["--echo", "--ollama-host", "http://x"]):
            with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
                with unittest.mock.patch("sys.stderr", io.StringIO()):
                    script.main(argv)


import unittest.mock  # noqa: E402

if __name__ == "__main__":
    unittest.main()
