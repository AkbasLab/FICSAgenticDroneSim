#!/usr/bin/env python3
"""Tests for the action executor: a skill flies on its own thread while the agent watches.

    python -m unittest discover tests

WHY THESE EXIST
---------------
Event-driven replanning (AUV-06, 5.2) needs the agent awake while a skill
flies: to see a target mid-search, to stop a leg when the battery says so.
These check that a started skill really flies on its own, that the agent can
read and stop it mid-flight, that nothing is lost in the hand-over -- an
abort asked for the instant a skill starts still lands -- and that on the
simulated clock it is all exactly as deterministic, and as timed, as calling
the skill directly.
"""

import os
import sys
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agentic_uav.control import skills as S  # noqa: E402
from agentic_uav.control.action_executor import ActionExecutor, ExecutorBusy  # noqa: E402
from agentic_uav.control.navigation import Waypoint  # noqa: E402
from agentic_uav.core.clock import RealClock  # noqa: E402
from agentic_uav.simulator.mock_adapter import MOCK_GROUND_Z, MockVehicleAdapter, MockWorld  # noqa: E402

G = MOCK_GROUND_Z
UP = S.TakeOffCommand(altitude_m=10)
OUT = S.GoToWaypointCommand(Waypoint(50, 0, 10))          # 50 m at 5 m/s: 10 s


def as_agent(world, body):
    """Run `body(executor, adapter)` on a thread on the world's timeline, as an agent would."""
    adapter = MockVehicleAdapter(world)
    executor = ActionExecutor(S.SkillRunner(adapter, "Drone1", world.clock))
    out = {}

    def run():
        with world.clock.participate():
            out["value"] = body(executor, adapter)

    thread = threading.Thread(target=run)
    thread.start()
    thread.join()
    executor.close()
    return out["value"], executor


def take_off(executor):
    executor.start(UP)
    assert executor.wait().result.ok


class StartAndWatchTests(unittest.TestCase):

    def test_start_returns_at_once_and_the_skill_flies_on(self):
        def body(executor, adapter):
            take_off(executor)
            t0 = executor.clock.now()
            started = executor.start(OUT)
            returned_at = executor.clock.now()
            executor.clock.sleep(2.0)                              # the agent does something else
            mid = adapter.get_pose("Drone1")
            busy_mid = executor.busy
            done = executor.wait()
            return t0, started, returned_at, mid, busy_mid, done

        (t0, started, returned_at, mid, busy_mid, done), _ = as_agent(MockWorld(), body)
        self.assertEqual(returned_at, t0)                          # no time passed in start()
        self.assertTrue(started.running)
        self.assertTrue(busy_mid)
        self.assertAlmostEqual(mid.x, 10.0, places=6)              # 2 s at 5 m/s, while the agent slept
        self.assertTrue(done.result.ok)
        self.assertAlmostEqual(done.result.ended_at - done.result.started_at, 10.0, places=6)
        self.assertFalse(done.running)

    def test_the_same_flight_as_calling_the_skills_directly(self):
        # The same outcomes, durations and positions. The only difference is
        # when the next skill starts: `wait` notices an ending at its next
        # slice, so each start comes at most one slice after the last ending
        # -- the agent's reaction time, during which the drone holds.
        from agentic_uav.control.action_executor import WAIT_SLICE_S
        plan = (UP, OUT, S.HoldPositionCommand(3.0), S.ReturnHomeCommand(), S.LandCommand())

        def via_executor(executor, adapter):
            out = []
            for command in plan:
                executor.start(command)
                out.append(executor.wait().result)
            return out

        through, _ = as_agent(MockWorld(), via_executor)
        world = MockWorld()
        runner = S.SkillRunner(MockVehicleAdapter(world), "Drone1", world.clock)
        direct = [runner.run(c) for c in plan]
        for i, (a, b) in enumerate(zip(through, direct)):
            with self.subTest(skill=a.skill.value):
                self.assertEqual(a.status, b.status)
                self.assertAlmostEqual(a.ended_at - a.started_at, b.ended_at - b.started_at, places=6)
                self.assertEqual(a.final_position, b.final_position)
                if i:
                    gap = a.started_at - through[i - 1].ended_at
                    self.assertGreaterEqual(gap, 0.0)
                    self.assertLessEqual(gap, WAIT_SLICE_S + 1e-9)

    def test_the_skill_is_on_the_timeline_before_start_returns(self):
        # Force the race: a clock whose participants take a moment (real
        # time) to join. Had `start` returned early, the agent's sleep would
        # have jumped time ahead with nothing flying.
        import contextlib
        from agentic_uav.core.clock import SimClock

        class SlowToJoin(SimClock):
            @contextlib.contextmanager
            def participate(self):
                if threading.current_thread().name.endswith("GO_TO_WAYPOINT"):
                    time.sleep(0.05)
                with super().participate():
                    yield

        world = MockWorld(clock=SlowToJoin())

        def body(executor, adapter):
            take_off(executor)
            executor.start(OUT)
            executor.clock.sleep(2.0)
            return adapter.get_pose("Drone1").x

        x, _ = as_agent(world, body)
        self.assertAlmostEqual(x, 10.0, places=6)

    def test_deterministic(self):
        def body(executor, adapter):
            take_off(executor)
            executor.start(OUT)
            executor.clock.sleep(3.3)
            executor.abort()
            executor.wait()
            return [(e.command.skill.value, e.started_at, e.result.ended_at, e.result.status.value)
                    for e in executor.history()]

        first, _ = as_agent(MockWorld(), body)
        second, _ = as_agent(MockWorld(), body)
        self.assertEqual(first, second)


class AbortTests(unittest.TestCase):

    def test_abort_mid_leg_stops_and_holds_there(self):
        def body(executor, adapter):
            take_off(executor)
            executor.start(OUT)
            executor.clock.sleep(4.0)
            asked = executor.abort()
            ended = executor.wait()
            stopped = adapter.get_pose("Drone1")
            executor.clock.sleep(5.0)
            return asked, ended, stopped, adapter.get_pose("Drone1")

        (asked, ended, stopped, later), _ = as_agent(MockWorld(), body)
        self.assertTrue(asked)
        self.assertTrue(ended.abort_requested)
        self.assertEqual(ended.result.status, S.SkillStatus.ABORTED)
        self.assertGreaterEqual(stopped.x, 20.0 - 1e-6)            # 4 s out
        self.assertLess(stopped.x, 21.0)                           # within a tick of the request
        self.assertEqual(later, stopped)                           # and held there

    def test_an_abort_the_instant_a_skill_starts_is_not_lost(self):
        def body(executor, adapter):
            take_off(executor)
            executor.start(OUT)
            executor.abort()                                       # before the skill's thread runs it
            return executor.wait(), adapter.get_pose("Drone1")

        for attempt in range(20):
            with self.subTest(attempt=attempt):
                (ended, where), _ = as_agent(MockWorld(), body)
                self.assertEqual(ended.result.status, S.SkillStatus.ABORTED)
                self.assertLess(where.x, 1.0)

    def test_abort_with_nothing_running(self):
        (asked, _), executor = as_agent(MockWorld(), lambda e, a: (e.abort(), None))
        self.assertFalse(asked)
        self.assertEqual(executor.history(), ())

        def after_a_skill(executor, adapter):
            take_off(executor)
            return executor.abort(), executor.current()

        (asked, latest), _ = as_agent(MockWorld(), after_a_skill)
        self.assertFalse(asked)
        self.assertFalse(latest.abort_requested)

    def test_the_skill_after_an_aborted_one_runs(self):
        # An abort must not linger and kill the next skill at birth.
        def body(executor, adapter):
            take_off(executor)
            executor.start(OUT)
            executor.clock.sleep(2.0)
            executor.abort()
            first = executor.wait().result
            executor.start(S.GoToWaypointCommand(Waypoint(30, 0, 10)))
            return first, executor.wait().result

        (first, second), _ = as_agent(MockWorld(), body)
        self.assertEqual(first.status, S.SkillStatus.ABORTED)
        self.assertTrue(second.ok, second)

    def test_an_abort_before_the_thread_reaches_the_skill_still_lands(self):
        # Force the race: the skill's thread pauses (in real time) before it
        # starts the skill, so the abort is certain to arrive first.
        world = MockWorld()
        inner = S.SkillRunner(MockVehicleAdapter(world), "Drone1", world.clock)

        class Slow:
            vehicle_id, clock = "Drone1", world.clock

            def clear_abort(self):
                inner.clear_abort()

            def request_abort(self, via=None):
                inner.request_abort(via)

            def run(self, command, clear_abort=True):
                time.sleep(0.05)
                return inner.run(command, clear_abort)

        executor = ActionExecutor(Slow(), clock=world.clock)
        out = {}

        def agent():
            with world.clock.participate():
                executor.start(UP)
                out["up"] = executor.wait().result
                executor.start(OUT)
                executor.abort()
                out["out"] = executor.wait().result

        thread = threading.Thread(target=agent)
        thread.start()
        thread.join()
        self.assertTrue(out["up"].ok)
        self.assertEqual(out["out"].status, S.SkillStatus.ABORTED)


class OneAtATimeTests(unittest.TestCase):

    def test_a_second_skill_is_refused_while_one_runs(self):
        def body(executor, adapter):
            take_off(executor)
            executor.start(OUT)
            try:
                executor.start(S.HoldPositionCommand(1.0))
                refused = False
            except ExecutorBusy:
                refused = True
            executor.wait()
            again = executor.start(S.HoldPositionCommand(1.0))      # fine once it has ended
            executor.wait()
            return refused, again.serial, len(executor.history())

        (refused, serial, count), _ = as_agent(MockWorld(), body)
        self.assertTrue(refused)
        self.assertEqual((serial, count), (3, 3))

    def test_wait_can_give_up_while_it_still_flies(self):
        def body(executor, adapter):
            take_off(executor)
            executor.start(OUT)
            early = executor.wait(timeout_s=3.0)
            return early.running, executor.wait().result.ok

        (still, ok), _ = as_agent(MockWorld(), body)
        self.assertTrue(still)
        self.assertTrue(ok)

    def test_not_a_command(self):
        with self.assertRaises(TypeError):
            ActionExecutor(S.SkillRunner(MockVehicleAdapter(MockWorld()), "Drone1")).start("TAKE_OFF")


class _Exploding:
    """A runner whose skill thread raises: a bug, not a flight outcome."""

    vehicle_id = "Drone1"

    def __init__(self, clock):
        self.clock = clock

    def clear_abort(self):
        pass

    def run(self, command, clear_abort=True):
        raise RuntimeError("boom")


class FailureTests(unittest.TestCase):

    def test_a_raising_skill_thread_is_recorded_not_lost(self):
        world = MockWorld()
        executor = ActionExecutor(_Exploding(world.clock), clock=world.clock)
        execution = executor.start(UP)
        executor.close()
        ended = executor.current()
        self.assertEqual(execution.serial, 1)
        self.assertFalse(ended.running)
        self.assertIsNone(ended.result)
        self.assertEqual(ended.error, "RuntimeError: boom")


class SkillRunnerClearAbortTests(unittest.TestCase):

    def test_a_pending_abort_is_kept_only_when_asked(self):
        world = MockWorld()
        runner = S.SkillRunner(MockVehicleAdapter(world), "Drone1", world.clock)
        self.assertTrue(runner.run(UP).ok)
        runner.request_abort()
        self.assertEqual(runner.run(S.HoldPositionCommand(1.0), clear_abort=False).status, S.SkillStatus.ABORTED)
        runner.request_abort()
        self.assertTrue(runner.run(S.HoldPositionCommand(1.0)).ok)            # the default clears it
        runner.request_abort()
        runner.clear_abort()
        self.assertTrue(runner.run(S.HoldPositionCommand(1.0), clear_abort=False).ok)


class RealClockTests(unittest.TestCase):

    def test_the_same_code_in_real_time(self):
        clock = RealClock()
        world = MockWorld(clock=clock)
        adapter = MockVehicleAdapter(world)
        adapter.take_control("Drone1")
        adapter.execute_primitive("Drone1", S.PrimitiveCommand.move_to_position(0, 0, G - 3, 10.0))
        runner = S.SkillRunner(adapter, "Drone1", clock, ground_z=G)
        executor = ActionExecutor(runner)
        began = time.monotonic()
        executor.start(S.GoToWaypointCommand(Waypoint(3, 0, 3), speed_mps=10.0))
        returned = time.monotonic() - began
        result = executor.wait().result
        executor.close()
        self.assertLess(returned, 0.2)                             # it did not fly the leg in start()
        self.assertTrue(result.ok, result)


if __name__ == "__main__":
    unittest.main()
