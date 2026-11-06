#!/usr/bin/env python3
"""docs/TESTING.md names a test for every item of AUV-15's 16.1, 16.2 and 16.4: each named test must exist.

    python -m unittest discover -s tests -p test_traceability.py

WHY THIS EXISTS
---------------
A map of what is tested is worth only as much as it is true. This reads every
`tests/<file>.py::<Class>::<test>` reference in docs/TESTING.md and finds it in
the test file's syntax tree, and checks every item AUV-15 lists has at least
one -- so renaming or deleting a test it names fails here, not silently.
"""

import ast
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC = os.path.join(ROOT, "docs", "TESTING.md")
REF = re.compile(r"`(tests/test_[a-z0-9_]+\.py)::([A-Za-z0-9_]+)::(test_[a-z0-9_]+)`")
UNIT = ("Task-cost calculation", "Tie breaking", "Task-lease expiration", "Message serialization",
        "Message expiration", "Packet-loss sampling", "Latency scheduling", "Role transitions", "Belief-state aging",
        "Geofence checks", "Battery checks", "Invalid LLM output handling")
SCENARIOS = ("Two agents allocate two tasks", "Four agents allocate four tasks",
             "One agent disappears and its task is reassigned", "A partition divides the team",
             "Delayed claims create a conflict and are resolved", "The relay agent fails and another assumes the role",
             "Malformed LLM output triggers fallback")
DETERMINISM = ("The whole run directory", "Network events", "Target placement", "Injected faults",
               "Deterministic policies", "The same model output")


def tests_in(path: str) -> set[tuple[str, str]]:
    with open(os.path.join(ROOT, path), encoding="utf-8") as h:
        tree = ast.parse(h.read())
    return {(c.name, f.name) for c in tree.body if isinstance(c, ast.ClassDef)
            for f in c.body if isinstance(f, ast.FunctionDef)}


def rows(text: str) -> dict[str, list[tuple[str, str, str]]]:
    out = {}
    for line in text.splitlines():
        if line.startswith("| ") and "`tests/" in line:
            out[line.split("|")[1].strip()] = REF.findall(line)
    return out


class TraceabilityTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(DOC, encoding="utf-8") as h:
            cls.text = h.read()
        cls.rows = rows(cls.text)

    def test_every_named_test_exists(self):
        refs = REF.findall(self.text)
        self.assertGreater(len(refs), 40)
        cache: dict[str, set] = {}
        for path, cls, name in refs:
            with self.subTest(test=f"{path}::{cls}::{name}"):
                self.assertTrue(os.path.isfile(os.path.join(ROOT, path)), path)
                found = cache.setdefault(path, tests_in(path))
                self.assertIn((cls, name), found)

    def test_every_item_has_a_test(self):
        for item in UNIT + SCENARIOS + DETERMINISM:
            with self.subTest(item=item):
                self.assertTrue(self.rows.get(item), f"{item}: no test named in docs/TESTING.md")

    def test_a_wrong_reference_would_be_caught(self):
        bad = "| Tie breaking | `tests/test_bids.py::RankTests::test_no_such_test` |"
        (path, cls, name), = rows(bad)["Tie breaking"]
        self.assertNotIn((cls, name), tests_in(path))


if __name__ == "__main__":
    unittest.main()
