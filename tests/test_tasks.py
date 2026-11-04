#!/usr/bin/env python3
"""Tests for agentic_uav.coordination.tasks: the work as explicit tasks (AUV-08, 8.1).

    python -m unittest discover tests

WHY THESE EXIST
---------------
Phase 8 divides a team mission between drones with no central assignment.
That needs the work written down as tasks every drone derives the same way
from the same brief, and a view of them per drone that only its own acts and
the messages it receives can change. These pin both: AUV-08's fields, what a
task may and may not become, versions that only go up, and a book that
refuses older news and logs every change.
"""

import dataclasses
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agentic_uav.coordination.tasks import (  # noqa: E402
    DEFAULT_CAPABILITIES,
    SEARCH,
    MissionTask,
    TaskBook,
    TaskStatus,
    TaskType,
    tasks_from_brief,
)
from agentic_uav.core.geometry import Region  # noqa: E402
from agentic_uav.experiments import scenarios  # noqa: E402

TEAM = scenarios.load_scenario("search_relay_001")
LIVE = scenarios.load_scenario("search_relay_live_small")


def task(**changes):
    base = MissionTask("search S1", TaskType.SEARCH_SECTOR, Region(40, -80, 120, 0), 1, frozenset({SEARCH}), 900.0)
    return dataclasses.replace(base, **changes)


class TaskTests(unittest.TestCase):

    def test_auv_08s_fields_and_a_version(self):
        self.assertEqual([f.name for f in dataclasses.fields(MissionTask)],
                         ["task_id", "task_type", "region", "priority", "required_capabilities", "deadline",
                          "status", "assigned_agent", "lease_expires_at", "version"])

    def test_the_types_auv_08_names(self):
        self.assertEqual({t.value for t in TaskType},
                         {"search_sector", "maintain_relay_point", "inspect_target", "return_to_base"})
        self.assertEqual({s.value for s in TaskStatus}, {"open", "claimed", "complete", "abandoned"})   # abandoned: Phase 9

    def test_a_claim_a_renewal_and_completion(self):
        t = task().claimed("Drone2", at=3.0, lease_s=10.0)
        self.assertEqual((t.status, t.assigned_agent, t.lease_expires_at, t.version),
                         (TaskStatus.CLAIMED, "Drone2", 13.0, 1))
        self.assertFalse(t.lease_expired(12.999))
        self.assertTrue(t.lease_expired(13.0))
        t = t.renewed(at=9.0, lease_s=10.0)
        self.assertEqual(t.lease_expires_at, 19.0)
        done = t.completed()
        self.assertEqual((done.status, done.assigned_agent, done.lease_expires_at), (TaskStatus.COMPLETE, "Drone2", None))
        self.assertFalse(done.lease_expired(1e9))

    def test_back_in_the_pool_one_version_on(self):
        t = task().claimed("Drone2", at=3.0, lease_s=10.0).reopened()
        self.assertEqual((t.status, t.assigned_agent, t.lease_expires_at, t.version), (TaskStatus.OPEN, None, None, 2))
        self.assertEqual(t.reopened().version, 3)

    def test_abandoned_only_from_open_and_a_claim_takes_it_back(self):
        gone = task().abandoned()
        self.assertEqual((gone.status, gone.assigned_agent, gone.lease_expires_at, gone.version),
                         (TaskStatus.ABANDONED, None, None, 1))
        self.assertEqual(gone.claimed("Drone3", 5.0, 10.0).status, TaskStatus.CLAIMED)      # someone could, after all
        for not_open in (task().claimed("Drone2", 0.0, 10.0), task().claimed("Drone2", 0.0, 10.0).completed(), gone):
            with self.assertRaisesRegex(ValueError, "only an open task is abandoned"):
                not_open.abandoned()
        with self.assertRaises(ValueError):
            task(status=TaskStatus.ABANDONED, assigned_agent="Drone1")
        self.assertNotIn(gone, TaskBook("Drone1", [gone]).open())

    def test_what_a_task_cannot_become(self):
        done = task().claimed("Drone2", at=0.0, lease_s=10.0).completed()
        for move in (lambda: done.claimed("Drone3", 1.0, 10.0), done.reopened, done.completed,
                     lambda: done.renewed(1.0, 10.0), lambda: task().renewed(1.0, 10.0), task().completed):
            with self.assertRaises(ValueError):
                move()
        # Refused for the reason, not only by the validation that would follow.
        with self.assertRaisesRegex(ValueError, "only a claimed task's lease is renewed"):
            task().renewed(1.0, 10.0)

    def test_malformed_tasks_are_refused(self):
        for changes in ({"task_id": ""}, {"task_type": "search"}, {"region": (0, 0, 1, 1)}, {"priority": -1},
                        {"priority": 1.5}, {"priority": True}, {"required_capabilities": {"search"}},
                        {"deadline": 0.0}, {"status": "open"}, {"version": 0}, {"version": True},
                        {"assigned_agent": "Drone1"}, {"lease_expires_at": 5.0},
                        {"status": TaskStatus.CLAIMED}, {"status": TaskStatus.CLAIMED, "assigned_agent": "Drone1"},
                        {"status": TaskStatus.COMPLETE},
                        {"status": TaskStatus.COMPLETE, "assigned_agent": "Drone1", "lease_expires_at": 3.0}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                task(**changes)

    def test_its_json(self):
        row = json.loads(json.dumps(task().claimed("Drone2", at=1.25, lease_s=10.0).as_json()))
        self.assertEqual(row, {"task_id": "search S1", "task_type": "search_sector", "region": [40, -80, 120, 0],
                               "priority": 1, "required_capabilities": ["search"], "deadline": 900.0,
                               "status": "claimed", "assigned_agent": "Drone2", "lease_expires_at": 11.25,
                               "version": 1})


class TeamMissionTests(unittest.TestCase):

    def test_one_open_search_per_sector_in_the_briefs_order(self):
        tasks = tasks_from_brief(TEAM.brief())
        self.assertEqual([t.task_id for t in tasks], ["search S1", "search S2", "search S3", "search S4"])
        for t, s in zip(tasks, TEAM.brief().sectors):
            self.assertEqual((t.task_type, t.region, t.status, t.assigned_agent, t.version),
                             (TaskType.SEARCH_SECTOR, s.region, TaskStatus.OPEN, None, 1))
            self.assertEqual(t.deadline, TEAM.mission.deadline_s)
            self.assertLessEqual(t.required_capabilities, DEFAULT_CAPABILITIES)

    def test_every_agent_derives_the_same_mission(self):
        self.assertEqual(tasks_from_brief(TEAM.brief()), tasks_from_brief(TEAM.brief()))
        self.assertEqual([t.task_id for t in tasks_from_brief(LIVE.brief())], ["search S1", "search S2"])

    def test_the_id_is_the_task_as_the_rule_policy_reads_it(self):
        for t in tasks_from_brief(TEAM.brief()):
            words = t.task_id.split()
            self.assertEqual(words[0], "search")
            self.assertIn(words[1], {s.id for s in TEAM.brief().sectors})

    def test_the_mission_generates_only_searches(self):
        self.assertEqual({t.task_type for t in tasks_from_brief(TEAM.brief())}, {TaskType.SEARCH_SECTOR})


class TaskBookTests(unittest.TestCase):

    def setUp(self):
        self.book = TaskBook("Drone2", tasks_from_brief(TEAM.brief()))

    def test_it_starts_as_the_mission(self):
        self.assertEqual(self.book.owner, "Drone2")
        self.assertEqual(len(self.book.open()), 4)
        self.assertEqual(self.book.held_by("Drone2"), ())
        self.assertEqual(self.book.log, [])
        self.assertTrue(self.book.knows("search S3"))
        self.assertFalse(self.book.knows("search S9"))

    def test_a_change_is_taken_and_logged(self):
        claimed = self.book.get("search S1").claimed("Drone1", at=1.0, lease_s=10.0)
        self.assertTrue(self.book.update(claimed, at=1.5, why="Drone1#3 claimed it"))
        self.assertEqual(self.book.get("search S1"), claimed)
        self.assertEqual(self.book.held_by("Drone1"), (claimed,))
        self.assertEqual(self.book.held_by("Drone2"), ())                       # held by whom it says
        self.assertEqual(len(self.book.open()), 3)
        (entry,) = self.book.log
        self.assertEqual(entry.as_json(), {
            "at": 1.5, "task_id": "search S1", "why": "Drone1#3 claimed it",
            "before": {"status": "open", "assigned_agent": None, "version": 1, "lease_expires_at": None},
            "after": {"status": "claimed", "assigned_agent": "Drone1", "version": 1, "lease_expires_at": 11.0}})

    def test_older_news_never_replaces_newer(self):
        t = self.book.get("search S1")
        newer = t.claimed("Drone1", 1.0, 10.0).reopened()                       # version 2, open
        self.assertTrue(self.book.update(newer, at=12.0, why="lease ran out"))
        stale = t.claimed("Drone3", 2.0, 10.0)                                   # version 1
        self.assertFalse(self.book.update(stale, at=13.0, why="a late claim"))
        self.assertEqual(self.book.get("search S1"), newer)
        self.assertEqual(len(self.book.log), 1)

    def test_no_change_is_not_logged(self):
        t = self.book.get("search S2")
        self.assertFalse(self.book.update(t, at=1.0, why="nothing"))
        self.assertEqual(self.book.log, [])

    def test_an_unknown_task_or_a_task_twice_is_refused(self):
        with self.assertRaises(KeyError):
            self.book.update(task(task_id="search S9"), at=1.0, why="?")
        with self.assertRaises(ValueError):
            TaskBook("Drone1", [task(), task()])

    def test_its_json(self):
        row = json.loads(json.dumps(self.book.as_json()))
        self.assertEqual(row["owner"], "Drone2")
        self.assertEqual([t["task_id"] for t in row["tasks"]], ["search S1", "search S2", "search S3", "search S4"])


class BoundaryTests(unittest.TestCase):

    def test_the_coordination_package_reaches_no_ground_truth(self):
        from test_sensing import boundary_violations
        folder = os.path.join(ROOT, "agentic_uav", "coordination")
        modules = [os.path.join(folder, f) for f in sorted(os.listdir(folder)) if f.endswith(".py")]
        self.assertIn(os.path.join(folder, "tasks.py"), modules)
        for path in modules:
            with self.subTest(module=os.path.basename(path)):
                self.assertEqual(boundary_violations(path, "agentic_uav.coordination"), [])


if __name__ == "__main__":
    unittest.main()
