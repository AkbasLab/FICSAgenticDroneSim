"""NavRL steers away from another drone it can see (needs torch and a NavRL checkout; skipped where they are missing)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    import numpy as np
    import torch  # noqa: F401
    from fics_drone.planners.navrl_planner import DEFAULT_NAVRL_DIR, NavRLPlanner
    AVAILABLE = os.path.isdir(os.environ.get("NAVRL_DIR", DEFAULT_NAVRL_DIR))
except ImportError:
    AVAILABLE = False


@unittest.skipUnless(AVAILABLE, "needs torch and a NavRL checkout")
class TestNavRLSeesPeers(unittest.TestCase):
    def test_a_drone_dead_ahead_changes_the_velocity_and_one_far_away_does_not(self):
        planner = NavRLPlanner()
        leg = planner.begin_leg((0.0, 0.0), (30.0, 0.0))
        free = np.array(leg.velocity((5.0, 0.0), (30.0, 0.0), []))
        near = planner.begin_leg((0.0, 0.0), (30.0, 0.0), None)
        near._peers_fn = lambda: [((7.0, 0.1), (-1.0, 0.0))]            # 2 m ahead, coming the other way
        blocked = np.array(near.velocity((5.0, 0.0), (30.0, 0.0), []))
        far = planner.begin_leg((0.0, 0.0), (30.0, 0.0), None)
        far._peers_fn = lambda: [((25.0, 0.0), (-1.0, 0.0))]            # 20 m ahead: out of NavRL's 4 m range
        unaffected = np.array(far.velocity((5.0, 0.0), (30.0, 0.0), []))
        self.assertGreater(np.linalg.norm(blocked - free), 0.2)
        self.assertLess(np.linalg.norm(unaffected - free), 0.05)


@unittest.skipUnless(AVAILABLE, "needs torch and a NavRL checkout")
class TestSeparationFilter(unittest.TestCase):
    def test_flying_past_a_parked_drone_keeps_the_separation_limit(self):
        planner = NavRLPlanner()
        planner.separation_m = 5.0
        leg = planner.begin_leg((0.0, 0.0), (30.0, 0.0), None)
        peer = np.array([15.0, 0.0])                    # parked on the line to the goal
        leg._peers_fn = lambda: [((15.0, 0.0), (0.0, 0.0))]
        pos, closest = np.array([0.0, 0.0]), 1e9
        for _ in range(400):
            pos = pos + np.array(leg.velocity(tuple(pos), (30.0, 0.0), [])) * 0.1
            closest = min(closest, float(np.linalg.norm(pos - peer)))
            if np.linalg.norm(pos - np.array([30.0, 0.0])) < 0.5:
                break
        self.assertGreaterEqual(closest, 4.9)
        self.assertLess(np.linalg.norm(pos - np.array([30.0, 0.0])), 0.6)    # and it still gets there

    def test_filter_leaves_a_distant_peer_alone_and_pushes_off_a_close_one(self):
        from fics_drone.planners.navrl_planner import keep_separation
        v = np.array([1.9, 0.0])
        far = keep_separation(np.array([0.0, 0.0]), v, [(30.0, 0.0)], 5.0)
        self.assertTrue(np.allclose(far, v))
        close = keep_separation(np.array([0.0, 0.0]), v, [(3.0, 0.0)], 5.0)
        self.assertLess(close[0], 0.0)                   # inside the limit it backs away


if __name__ == "__main__":
    unittest.main()
