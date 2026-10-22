#!/usr/bin/env python3
"""Tests of the tests: no test class may shadow a unittest.TestCase method.

    python -m unittest discover tests

WHY THIS EXISTS
---------------
Phase 5, step 4: a helper in `tests/test_rule_policy.py` was named `fail`.
That shadows `TestCase.fail`, which every `assertEqual`, `assertIn` and the
rest call to report a failure -- so the helper answered "assertion failed"
by returning a value, and every assertion in that class passed whatever the
code did. A mutation test surviving against an obviously relevant test is
what showed it. A shadowed name fails silently by its nature, so it is
checked here, for every test file, once and for all.
"""

import ast
import glob
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALLOWED = {"setUp", "tearDown", "setUpClass", "tearDownClass", "run"}    # meant to be overridden


class HygieneTests(unittest.TestCase):

    def test_no_test_class_shadows_a_testcase_method(self):
        reserved = {n for n in dir(unittest.TestCase) if not n.startswith("__")} - ALLOWED
        shadows = []
        for path in sorted(glob.glob(os.path.join(ROOT, "tests", "*.py"))):
            tree = ast.parse(open(path, encoding="utf-8").read(), path)
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    shadows += [f"{os.path.basename(path)}: {node.name}.{item.name}" for item in node.body
                                if isinstance(item, ast.FunctionDef) and item.name in reserved]
        self.assertEqual(shadows, [])

    def test_the_check_sees_a_shadow(self):
        tree = ast.parse("class T:\n    def fail(self, x):\n        return x\n")
        names = [item.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef) for item in node.body]
        self.assertIn("fail", {n for n in dir(unittest.TestCase)} & set(names))


if __name__ == "__main__":
    unittest.main()
