#!/usr/bin/env python3
"""Tests for the freeze (AUV-16 17.4): the frozen files are as their latest version says, and a change shows.

    python -m unittest discover -s tests -p test_freeze.py

WHY THESE EXIST
---------------
After the pilots, nothing that decides how the drones fly, how the model is asked, or how a run is scored may change
silently before or during the main experiment. The first test IS the freeze: in every run of the suite, and so in
CI on every push, the repository must be its latest frozen version (configs/frozen.toml). The others show the check
able to fail -- a frozen file edited, added or removed; a version undated, unnumbered or without a note -- and that
the one way through is a new dated version with a note; and that a checkout's line endings never count.
"""

import contextlib
import io
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agentic_uav.experiments import freeze as F  # noqa: E402


class TheFreezeTests(unittest.TestCase):
    def test_the_repository_is_its_latest_frozen_version(self):
        self.assertEqual(F.check(ROOT), [])

    def test_version_one_is_the_freeze_after_the_pilots(self):
        v = F.load(ROOT)[0]
        self.assertEqual((v["number"], v["date"]), (1, "2026-11-08"))
        self.assertIn("pilot", v["note"])
        for rel in ("agentic_uav/agents/llm_context.py", "agentic_uav/agents/llm_tools.py",
                    "agentic_uav/agents/rule_policy.py", "agentic_uav/coordination/keepout.py",
                    "agentic_uav/safety/guardian.py", "agentic_uav/experiments/metrics.py",
                    "configs/llm/default.toml", "configs/network/moderate.toml", "configs/network/severe.toml",
                    "configs/scenarios/search_pair_001.toml", "configs/scenarios/search_relay_001.toml",
                    "docs/METRICS.md", "docs/CONDITIONS.md"):
            self.assertIn(rel, v["files"])
        self.assertFalse([r for r in v["files"] if r.startswith("configs/experiments/") or r.endswith(".pyc")
                          or "__pycache__" in r or r == "configs/frozen.toml"])


class AbleToFailTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        for entry in F.SCOPE + ("configs/frozen.toml",):
            src, dst = os.path.join(ROOT, entry), os.path.join(self.root, entry)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if os.path.isdir(src):
                shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            elif os.path.isfile(src):
                shutil.copy2(src, dst)
        self.assertEqual(F.check(self.root), [])

    def path(self, rel):
        return os.path.join(self.root, rel)

    def test_a_frozen_file_edited_added_or_removed_fails(self):
        with io.open(self.path("configs/network/severe.toml"), "a", encoding="utf-8", newline="\n") as h:
            h.write("# a quiet tweak\n")
        with io.open(self.path("agentic_uav/agents/new_trick.py"), "w", encoding="utf-8") as h:
            h.write("X = 1\n")
        os.remove(self.path("docs/METRICS.md"))
        got = F.check(self.root)
        self.assertIn("configs/network/severe.toml: changed since frozen version 1", got)
        self.assertIn("agentic_uav/agents/new_trick.py: new in the frozen scope since version 1", got)
        self.assertIn("docs/METRICS.md: frozen in version 1, now missing", got)
        self.assertIn(F.COMMAND, got[-1])

    def test_outside_the_scope_nothing_counts(self):
        os.makedirs(self.path("configs/experiments"), exist_ok=True)
        with io.open(self.path("configs/experiments/phase18_main.toml"), "w", encoding="utf-8") as h:
            h.write("[batch]\n")
        os.makedirs(self.path("agentic_uav/agents/__pycache__"), exist_ok=True)
        with io.open(self.path("agentic_uav/agents/__pycache__/x.cpython-310.pyc"), "wb") as h:
            h.write(b"\0")
        self.assertEqual(F.check(self.root), [])

    def test_line_endings_alone_are_no_change(self):
        p = self.path("agentic_uav/coordination/keepout.py")
        with open(p, "rb") as h:
            data = h.read()
        with open(p, "wb") as h:
            h.write(data.replace(b"\n", b"\r\n"))
        self.assertEqual(F.check(self.root), [])

    def test_the_way_through_is_a_new_dated_version_with_a_note(self):
        with io.open(self.path("configs/recovery/default.toml"), "a", encoding="utf-8", newline="\n") as h:
            h.write("# a defect fixed\n")
        self.assertTrue(F.check(self.root))
        for note in ("", "   "):
            with self.assertRaises(ValueError):
                F.add_version(self.root, note, "2026-12-01")
        with self.assertRaises(ValueError):                    # dated before version 1
            F.add_version(self.root, "fixed", "2026-11-01")
        v = F.add_version(self.root, "the recovery rule's defect, found in Phase 18 run 12", "2026-12-01")
        self.assertEqual((v["number"], v["date"]), (2, "2026-12-01"))
        self.assertEqual(F.check(self.root), [])
        self.assertEqual([x["number"] for x in F.load(self.root)], [1, 2])
        self.assertEqual(F.load(self.root)[0]["files"], F.load(ROOT)[0]["files"])     # version 1 kept as it was
        with self.assertRaises(ValueError):                    # nothing changed since version 2
            F.add_version(self.root, "again", "2026-12-02")

    def test_a_version_undated_unnumbered_or_without_a_note_fails(self):
        v1 = F.load(self.root)[0]
        cases = (({**v1, "date": "8 Nov 2026"}, "no date"), ({**v1, "date": "2026-13-40"}, "not a date"),
                 ({**v1, "number": 2}, "numbered"), ({**v1, "note": " "}, "no note"), ({**v1, "files": {}}, "no files"))
        for bad, word in cases:
            self.assertTrue(any(word in p for p in F.version_problems([bad])), (word, F.version_problems([bad])))
        later = {**v1, "number": 2, "date": "2026-11-01", "note": "x"}
        self.assertTrue(any("before version 1" in p for p in F.version_problems([v1, later])))
        os.remove(self.path("configs/frozen.toml"))
        self.assertEqual(F.check(self.root), ["no frozen version in " + F.FROZEN])


class CommandTests(unittest.TestCase):
    def test_the_command_checks_and_records(self):
        sys.path.insert(0, os.path.join(ROOT, "scripts"))
        import freeze as cmd
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root)
        os.makedirs(os.path.join(root, "configs", "llm"))
        os.makedirs(os.path.join(root, "docs"))
        os.makedirs(os.path.join(root, "agentic_uav"))
        for rel in ("configs/llm/default.toml", "docs/METRICS.md", "docs/CONDITIONS.md", "agentic_uav/__init__.py"):
            shutil.copy2(os.path.join(ROOT, rel), os.path.join(root, rel))
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(cmd.main(["--root", root]), 1)                   # no freeze yet
            self.assertEqual(cmd.main(["--root", root, "--note", "first"]), 0)
            self.assertEqual(cmd.main(["--root", root]), 0)
            self.assertEqual(cmd.main(["--root", root, "--note", "nothing new"]), 1)
        self.assertIn("frozen version 1", out.getvalue())


if __name__ == "__main__":
    unittest.main()
