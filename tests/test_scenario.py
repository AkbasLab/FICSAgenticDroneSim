#!/usr/bin/env python3
"""Tests for scenarios: the geometry, the data model, the strict TOML loader, the brief.

    python -m unittest discover tests

WHY THESE EXIST
---------------
AUV-05 (4.4) puts every experimental condition in a scenario file, and the
factorial later becomes a loop over files. So a file must say exactly what it
means: these check that a well-formed scenario loads as written, that every
kind of mistake is refused -- with all the problems listed, not just the
first -- and that what a controller is handed carries no ground truth.
"""

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agentic_uav.core.geometry import Polygon, Region  # noqa: E402
from agentic_uav.core.scenario import MissionBrief, Scenario, ScenarioError  # noqa: E402
from agentic_uav.experiments import scenarios  # noqa: E402
from agentic_uav.experiments.runner import load_toml  # noqa: E402

CANONICAL = os.path.join(ROOT, "configs", "scenarios", "search_relay_001.toml")


def canonical_data():
    return load_toml(CANONICAL)


def problems_of(data):
    """The problems parse() reports for `data`; fails if it accepts it."""
    try:
        scenarios.parse(data, "test")
    except ScenarioError as exc:
        return exc.problems
    raise AssertionError("the scenario was accepted")


class GeometryTests(unittest.TestCase):

    def test_region_area_and_overlap(self):
        a, b = Region(0, 0, 10, 10), Region(10, 0, 20, 10)
        self.assertEqual(a.area, 100)
        self.assertFalse(a.overlaps(b))                       # touching is not overlapping
        self.assertTrue(a.overlaps(Region(9, 9, 12, 12)))

    def test_region_is_the_same_class_navigation_and_skills_use(self):
        from agentic_uav.control import navigation, skills
        self.assertIs(navigation.Region, Region)
        self.assertIs(skills.Region, Region)

    def test_polygon_contains_inside_outside_and_boundary(self):
        square = Polygon(((0, 0), (10, 0), (10, 10), (0, 10)))
        self.assertTrue(square.contains(5, 5))
        self.assertTrue(square.contains(10, 5))               # boundary counts as inside
        self.assertTrue(square.contains(0, 0))
        self.assertFalse(square.contains(10.01, 5))
        self.assertEqual(square.area, 100)

    def test_concave_polygon(self):
        # An L shape: the notch at (7, 7) is outside.
        ell = Polygon(((0, 0), (10, 0), (10, 4), (4, 4), (4, 10), (0, 10)))
        self.assertTrue(ell.contains(2, 8))
        self.assertTrue(ell.contains(8, 2))
        self.assertFalse(ell.contains(7, 7))
        self.assertEqual(ell.area, 64)

    def test_a_path_that_crosses_and_one_that_does_not(self):
        zone = Polygon(((15, -15), (35, -15), (35, 15), (15, 15)))
        self.assertTrue(zone.crosses((0, 0), (50, 0)))        # straight through
        self.assertTrue(zone.crosses((0, 0), (20, 0)))        # ends inside
        self.assertTrue(zone.crosses((20, 0), (30, 5)))       # wholly inside: cuts no edge
        self.assertFalse(zone.crosses((0, 20), (50, 20)))     # passes north of it
        self.assertTrue(zone.crosses((0, 15), (50, 15)))      # grazes its edge: refused
        self.assertFalse(zone.crosses((0, 0), (10, 30)))

    def test_degenerate_polygons_are_refused(self):
        with self.assertRaises(ValueError):
            Polygon(((0, 0), (1, 1)))
        with self.assertRaises(ValueError):
            Polygon(((0, 0), (1, 1), (2, 2)))                 # collinear: no area


class CanonicalScenarioTests(unittest.TestCase):

    def setUp(self):
        self.s = scenarios.load_scenario("search_relay_001")

    def test_it_is_auv05s_mission(self):
        s = self.s
        self.assertEqual(s.scenario_id, "search_relay_001")
        self.assertEqual(s.random_seed, 17)
        self.assertEqual(s.mission.deadline_s, 900)
        self.assertEqual(s.mission.required_coverage, 0.95)
        self.assertEqual(s.mission.targets_to_find, 2)
        self.assertEqual(s.network.profile, "perfect")
        self.assertEqual(len(s.sectors), 4)                   # four sectors
        self.assertEqual(len(s.vehicles), 4)                  # two to four drones
        self.assertEqual(s.targets.count, 2)                  # two targets
        self.assertEqual(len(s.restricted_zones), 1)          # one restricted region
        self.assertEqual(s.faults, ())

    def test_starts_are_the_spawn_layout(self):
        self.assertEqual([(v.start_x, v.start_y) for v in self.s.vehicles],
                         [(0, 0), (4, 0), (8, 0), (12, 0)])

    def test_the_far_sectors_are_out_of_radio_range(self):
        # The relay requirement: no point of S3 or S4 is within range of the base.
        base, r = self.s.base, self.s.network.communication_range_m
        for sector in self.s.sectors:
            reg = sector.region
            nearest_x = min(max(base.x, reg.x_min), reg.x_max)
            nearest_y = min(max(base.y, reg.y_min), reg.y_max)
            nearest = ((nearest_x - base.x) ** 2 + (nearest_y - base.y) ** 2) ** 0.5
            with self.subTest(sector=sector.id):
                if sector.id in ("S3", "S4"):
                    self.assertGreater(nearest, r)
                else:
                    self.assertLess(nearest, r)

    def test_the_restricted_zone_blocks_the_direct_path_to_the_far_sectors(self):
        zone = self.s.restricted_zones[0].polygon
        for v in self.s.vehicles:
            self.assertTrue(zone.crosses((v.start_x, v.start_y), (160.0, 0.0)), v.id)

    def test_the_brief_carries_no_ground_truth(self):
        brief = self.s.brief()
        self.assertIsInstance(brief, MissionBrief)
        self.assertFalse(hasattr(brief, "targets"))
        self.assertFalse(hasattr(brief, "random_seed"))
        self.assertEqual(brief.sectors, self.s.sectors)
        self.assertEqual(brief.mission.targets_to_find, 2)    # how many: public

    def test_loading_by_id_or_by_path_is_the_same(self):
        self.assertEqual(scenarios.load_scenario(CANONICAL), self.s)


class StrictLoaderTests(unittest.TestCase):

    def test_an_unknown_key_is_refused(self):
        data = canonical_data()
        data["mission"]["dead_line_s"] = 900                  # a typo
        problems = problems_of(data)
        self.assertTrue(any("unknown key 'dead_line_s'" in p for p in problems), problems)

    def test_a_missing_key_is_refused(self):
        data = canonical_data()
        del data["battery"]["reserve"]
        self.assertTrue(any("missing 'reserve'" in p for p in problems_of(data)))

    def test_a_wrong_type_is_refused(self):
        data = canonical_data()
        data["mission"]["targets_to_find"] = 2.0              # not an int
        data["random_seed"] = True                            # a bool is not an int
        problems = problems_of(data)
        self.assertTrue(any("targets_to_find: expected int" in p for p in problems), problems)
        self.assertTrue(any("random_seed: expected int" in p for p in problems), problems)

    def test_every_problem_is_reported_at_once(self):
        data = canonical_data()
        data["mission"]["required_coverage"] = 1.5
        data["network"]["communication_range_m"] = 0
        data["battery"]["reserve"] = 150
        data["sectors"][1]["bounds"] = [100.0, -10.0, 130.0, 10.0]   # overlaps S1 and S3
        data["vehicles"][1]["start"] = [0.5, 0.0]                    # 0.5 m from Drone1
        with self.assertRaises(ScenarioError) as ctx:
            scenarios.parse(data, "test")
        joined = "\n".join(ctx.exception.problems)
        for expected in ("required_coverage", "communication_range_m", "battery.reserve",
                         "overlap", "under min_separation_m"):
            self.assertIn(expected, joined)
        self.assertGreaterEqual(len(ctx.exception.problems), 5)

    def test_a_start_must_be_on_the_ground(self):
        data = canonical_data()
        data["vehicles"][0]["start"] = [0.0, 0.0, -5.0]
        self.assertTrue(any("third value must be 0" in p for p in problems_of(data)))
        data["vehicles"][0]["start"] = [0.0, 0.0]             # [x, y] is fine
        scenarios.parse(data, "test")

    def test_nothing_starts_or_is_placed_in_a_restricted_zone(self):
        data = canonical_data()
        data["vehicles"][3]["start"] = [20.0, 0.0]
        data["base"]["position"] = [25.0, 5.0]
        data["targets"].update(placement="fixed", fixed=[[25.0, 0.0], [60.0, -40.0]])
        joined = "\n".join(problems_of(data))
        self.assertIn("Drone4 starts inside restricted zone R1", joined)
        self.assertIn("the base is inside restricted zone R1", joined)
        self.assertIn("fixed target 0 at (25.0, 0.0) is in no sector", joined)

    def test_fixed_targets(self):
        data = canonical_data()
        data["targets"].update(placement="fixed", fixed=[[60.0, -40.0], [160.0, 40.0]])
        s = scenarios.parse(data, "test")
        self.assertEqual(s.targets.fixed, ((60.0, -40.0), (160.0, 40.0)))
        data["targets"]["fixed"] = [[60.0, -40.0]]            # one position for count = 2
        self.assertTrue(any("targets.fixed has 1 positions" in p for p in problems_of(data)))

    def test_more_to_find_than_exist(self):
        data = canonical_data()
        data["mission"]["targets_to_find"] = 3
        self.assertTrue(any("only 2 targets exist" in p for p in problems_of(data)))

    def test_phase_4_only_knows_the_perfect_network_and_no_line_of_sight(self):
        data = canonical_data()
        data["network"]["profile"] = "severe"
        data["detection"]["line_of_sight"] = True
        joined = "\n".join(problems_of(data))
        self.assertIn("network.profile 'severe'", joined)
        self.assertIn("line_of_sight", joined)

    def test_a_fault_needs_a_kind(self):
        data = canonical_data()
        data["faults"] = [{"drone": "Drone2"}]
        self.assertTrue(any("fault 0 has no 'kind'" in p for p in problems_of(data)))

    def test_files_that_do_not_parse_or_do_not_exist(self):
        with self.assertRaises(ScenarioError):
            scenarios.load_scenario("no_such_scenario")
        folder = tempfile.mkdtemp()
        try:
            bad = os.path.join(folder, "bad.toml")
            with open(bad, "w", encoding="utf-8") as h:
                h.write("scenario_id = \n")
            with self.assertRaises(ScenarioError) as ctx:
                scenarios.load_scenario(bad)
            self.assertIn("not valid TOML", str(ctx.exception))
        finally:
            import shutil
            shutil.rmtree(folder, ignore_errors=True)

    def test_a_scenario_built_directly_is_validated_too(self):
        s = scenarios.load_scenario("search_relay_001")
        fields = {f: getattr(s, f) for f in s.__dataclass_fields__}
        fields["vehicles"] = ()
        with self.assertRaises(ScenarioError):
            Scenario(**fields)


if __name__ == "__main__":
    unittest.main()
