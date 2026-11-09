#!/usr/bin/env python3
"""Tests for Phase 18's held-out seeds (AUV-16 17.4, 18.2): derived from the freeze, never a development seed.

    python -m unittest discover -s tests -p test_heldout.py

WHY THESE EXIST
---------------
A held-out result is only held out if its seeds were fixed before anything flew on them and were not picked.
configs/seeds/heldout.toml was drawn from freeze version 1 (committed in 62702e8, before the draw; git shows the
order): these recompute the seeds from configs/frozen.toml's version 1 -- in every suite and in CI, with no git
history needed -- and hold them to the rules: 20 test seeds and 10 reserves, all different, none a development
seed (1-20, 17), all in 1000..999999. And the derivation itself: the same digest always gives the same seeds, a
different freeze different ones.
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agentic_uav.experiments import freeze as F  # noqa: E402
from agentic_uav.experiments import heldout as H  # noqa: E402
from agentic_uav.experiments.runner import load_toml  # noqa: E402


class HeldOutTests(unittest.TestCase):
    def setUp(self):
        self.test, self.reserve = H.load_heldout(ROOT)
        self.v1 = F.load(ROOT)[0]

    def test_they_are_what_freeze_version_1_gives(self):
        self.assertEqual((self.test, self.reserve), H.draw(H.freeze_digest(self.v1)))
        data = load_toml(os.path.join(ROOT, H.HELDOUT))["heldout"]
        self.assertEqual(data["from_freeze_version"], 1)
        self.assertEqual(data["freeze_digest"], H.freeze_digest(self.v1))

    def test_twenty_test_seeds_ten_reserves_none_a_development_seed(self):
        seeds = self.test + self.reserve
        self.assertEqual((len(self.test), len(self.reserve)), (20, 10))
        self.assertEqual(len(set(seeds)), 30)
        self.assertFalse(set(seeds) & (set(range(1, 21)) | {17}))
        self.assertTrue(all(isinstance(s, int) and 1000 <= s <= 999_999 for s in seeds))

    def test_the_derivation_is_fixed_and_follows_the_freeze(self):
        d = H.freeze_digest(self.v1)
        self.assertEqual(H.draw(d), H.draw(d))
        other = {**self.v1, "note": self.v1["note"] + " "}
        self.assertNotEqual(H.draw(H.freeze_digest(other))[0], self.test)
        # A development seed or a repeat that comes up is passed over, never kept: a narrow range forces both.
        old = (H.LOW, H.HIGH)
        try:
            H.LOW, H.HIGH = 1, 55                      # 35 that are not development seeds, for 30
            test, reserve = H.draw(d)
            H.LOW, H.HIGH = 1, 49                      # 29: too few, refused rather than searched for ever
            with self.assertRaises(ValueError):
                H.draw(d)
        finally:
            H.LOW, H.HIGH = old
        self.assertEqual(len(set(test + reserve)), 30)
        self.assertFalse(set(test + reserve) & H.DEVELOPMENT)

    def test_the_seeds_file_is_frozen(self):
        self.assertIn(H.HELDOUT, F.load(ROOT)[-1]["files"])


if __name__ == "__main__":
    unittest.main()
