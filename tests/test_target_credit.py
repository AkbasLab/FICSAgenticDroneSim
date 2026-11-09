"""GMB: an agent's report says which targets it sensed itself and which of those it confirmed itself, apart from
what teammates told it. `target_found` alone returns the first confirmed target, which can be a teammate's. Mock-only."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fics_drone.agents.belief import Belief
from fics_drone.agents.belief_schema import MissionBelief, SelfState, TargetSighting


def _belief(sightings):
    b = Belief(self_state=SelfState(position=(0.0, 0.0, 0.0), elapsed_s=0.0, battery_s=600.0),
               mission=MissionBelief(sector_id="A"))
    for s in sightings:
        b.mission.targets_known[s.target_id] = s
    return b


def _sighting(tid, confirmed, source):
    return TargetSighting(target_id=tid, local_position=(0.0, 0.0, 8.0), first_seen_t=0.0, confirmed=confirmed, source=source)


class TargetCreditTests(unittest.TestCase):
    def test_a_teammates_find_does_not_hide_this_drones_own(self):
        b = _belief([_sighting("T3", True, "message"), _sighting("T4", True, "sensor")])
        self.assertEqual(b.target_found, "T3")
        self.assertEqual(b.targets_sensed, ("T4",))
        self.assertEqual(b.targets_confirmed_by_self, ("T4",))

    def test_a_sighting_whose_report_hold_failed_is_sensed_but_not_confirmed(self):
        b = _belief([_sighting("T1", False, "sensor")])
        self.assertIsNone(b.target_found)
        self.assertEqual(b.targets_sensed, ("T1",))
        self.assertEqual(b.targets_confirmed_by_self, ())

    def test_nothing_known_gives_empty(self):
        b = _belief([])
        self.assertEqual(b.targets_sensed, ())
        self.assertEqual(b.targets_confirmed_by_self, ())


if __name__ == "__main__":
    unittest.main()
