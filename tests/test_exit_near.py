"""A zone that switches on over an aircraft in a narrow street: leave by the near side even if a keep-out's margin is touched,
rather than fly the length of the zone."""
import unittest

from fics_drone.agents.belief import Belief
from fics_drone.agents.belief_schema import MissionBelief, SelfState
from fics_drone.agents.safety_guardian import Command, FallbackAction, SafetyGuardian, SafetyLimits
from fics_drone.core.obstacles import TreeObstacle
from fics_drone.core.scenario import NoFlyZone


def _tree(x, y, r):
    return TreeObstacle(x=x, y=y, z_bottom=0.0, z_top=25.0, trunk_r=r, crown_r=r, crown_from_frac=0.0)


class ExitNearTests(unittest.TestCase):
    def _exit(self, trees):
        zone = NoFlyZone("Z", 20.0, 40.0, 20.0, 40.0, active_from_s=60.0, active_until_s=120.0)
        g = SafetyGuardian(limits=SafetyLimits(restricted_zones=[zone], obstacles=trees, geofence_half_extent_m=200.0, obstacle_margin_m=3.0))
        belief = Belief(self_state=SelfState(position=(39.5, 30.0, 12.0), elapsed_s=70.0, battery_s=1000.0),
                        mission=MissionBelief(sector_id="A", search_queue=[]))
        ev = g.evaluate(Command(kind="fly", target=(0.0, 0.0, 12.0), speed_mps=5.0, timeout_s=30.0), belief)
        self.assertEqual(ev.fallback, FallbackAction.EXIT_ZONE)
        return ev.command.target

    def test_near_exit_that_touches_only_the_margin_beats_a_long_way_through_the_zone(self):
        # trees close up the east side's margin and stand over the north and south ways out of a long zone
        trees = [_tree(47.0, 30.0, 2.5)]
        tx, ty, _ = self._exit(trees)
        self.assertGreater(tx, 40.0)                              # east, out of the zone, not across it

    def test_a_margin_clear_exit_is_still_preferred_when_it_is_about_as_near(self):
        tx, ty, _ = self._exit([])
        self.assertGreater(tx, 40.0)


if __name__ == "__main__":
    unittest.main()
