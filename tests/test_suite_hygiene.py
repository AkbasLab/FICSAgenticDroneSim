#!/usr/bin/env python3
"""Tests of the tests: no test class may shadow a unittest.TestCase attribute.

    python -m unittest discover tests

WHY THIS EXISTS
---------------
Twice in Phase 5:

* step 4: a helper in `tests/test_rule_policy.py` was named `fail`. That
  shadows `TestCase.fail`, which every `assertEqual`, `assertIn` and the rest
  call to report a failure -- so the helper answered "assertion failed" by
  returning a value, and every assertion in that class passed whatever the
  code did. A mutation surviving against a plainly relevant test showed it.
* step 5: `cls.run = ...` in `tests/test_single_agent_exit.py` replaced
  `TestCase.run`, which the runner calls; that one failed loudly.

A shadowed name can fail silently by its nature, so it is checked here for
every test file: methods defined in a test class, names assigned in its
body, and attributes set on `self` or `cls` inside it.
"""

import ast
import glob
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALLOWED = {"setUp", "tearDown", "setUpClass", "tearDownClass", "maxDiff", "longMessage"}
RESERVED = {n for n in dir(unittest.TestCase) if not n.startswith("__")} - ALLOWED


def _is_test_class(cls: ast.ClassDef, known: set[str]) -> bool:
    """Derives from TestCase, directly or through a test class defined earlier in the file.

    Other classes in test files -- fakes, stand-ins, stubs with a `run` of
    their own -- are not test cases and may use any names they like.
    """
    for base in cls.bases:
        if isinstance(base, ast.Name) and (base.id == "TestCase" or base.id in known):
            return True
        if isinstance(base, ast.Attribute) and base.attr == "TestCase":
            return True
    return False


def shadows_in(source: str, name: str = "<test>") -> list[str]:
    """Every TestCase attribute a test class in `source` would shadow."""
    found = []
    known: set[str] = set()
    tree = ast.parse(source, name)
    classes = sorted((n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)), key=lambda n: n.lineno)
    for cls in classes:
        if not _is_test_class(cls, known):
            continue
        known.add(cls.name)
        for item in cls.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name in RESERVED:
                found.append(f"{name}: {cls.name}.{item.name} (method)")
            if isinstance(item, ast.Assign):
                found += [f"{name}: {cls.name}.{t.id} (class attribute)" for t in item.targets
                          if isinstance(t, ast.Name) and t.id in RESERVED]
        for node in ast.walk(cls):
            if isinstance(node, ast.Assign):
                found += [f"{name}: {cls.name}.{t.attr} (set on {t.value.id})" for t in node.targets
                          if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name)
                          and t.value.id in ("self", "cls") and t.attr in RESERVED]
    return found


class HygieneTests(unittest.TestCase):

    def test_no_test_class_shadows_a_testcase_attribute(self):
        shadows = []
        for path in sorted(glob.glob(os.path.join(ROOT, "tests", "*.py"))):
            shadows += shadows_in(open(path, encoding="utf-8").read(), os.path.basename(path))
        self.assertEqual(shadows, [])

    def test_the_check_sees_each_kind_of_shadow(self):
        for source in ("class T(unittest.TestCase):\n    def fail(self, x):\n        return x\n",
                       "class T(unittest.TestCase):\n    run = None\n",
                       "class T(TestCase):\n    @classmethod\n    def setUpClass(cls):\n        cls.run = 1\n",
                       "class T(unittest.TestCase):\n    pass\nclass U(T):\n    def setUp(self):\n"
                       "        self.assertTrue = print\n"):
            with self.subTest(source=source):
                self.assertNotEqual(shadows_in(source), [])
        # Not shadows: an ordinary name, and a `run` on a class that is not a test case.
        self.assertEqual(shadows_in("class T(unittest.TestCase):\n    def setUp(self):\n        self.flight = 1\n"), [])
        self.assertEqual(shadows_in("class FakeRunner:\n    def run(self, command):\n        return command\n"), [])


if __name__ == "__main__":
    unittest.main()
