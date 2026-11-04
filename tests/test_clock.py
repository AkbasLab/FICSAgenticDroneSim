#!/usr/bin/env python3
"""Tests for agentic_uav.core.clock: real time, and one simulated timeline.

    python -m unittest discover tests

WHY THESE EXIST
---------------
Every skill has a timeout and every result a start and end time (AUV-04, 3.3),
measured on a clock. In the mock that clock is simulated, and several drone
threads must share it: a separation check between two drones compares their
positions at one instant, which is meaningless if each thread kept its own
time. These pin the rule that makes a shared simulated timeline deterministic:
time moves only when every participant is waiting, and then to the earliest
wake-up.
"""

import os
import sys
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agentic_uav.core.clock import Clock, RealClock, SimClock  # noqa: E402


class RealClockTests(unittest.TestCase):

    def test_is_a_clock_and_moves(self):
        clock = RealClock()
        self.assertIsInstance(clock, Clock)
        # monotonic() can be coarse: GetTickCount64 on Windows ticks every
        # 15.6 ms, so a 10 ms sleep sometimes read as 0. Sleep well past one
        # tick and allow one tick of error.
        tick = time.get_clock_info("monotonic").resolution
        t0 = clock.now()
        clock.sleep(0.05)
        self.assertGreaterEqual(clock.now() - t0, 0.05 - tick)

    def test_negative_sleep_does_not_raise(self):
        RealClock().sleep(-1.0)


class SimClockSingleThreadTests(unittest.TestCase):

    def test_is_a_clock(self):
        self.assertIsInstance(SimClock(), Clock)

    def test_sleep_advances_instantly(self):
        clock = SimClock(start=100.0)
        started = time.monotonic()
        clock.sleep(3600.0)
        self.assertEqual(clock.now(), 3700.0)
        self.assertLess(time.monotonic() - started, 0.5)

    def test_negative_sleep_is_zero(self):
        clock = SimClock()
        clock.sleep(-5.0)
        self.assertEqual(clock.now(), 0.0)

    def test_advance_from_outside(self):
        clock = SimClock()
        clock.advance(2.5)
        self.assertEqual(clock.now(), 2.5)


class SimClockSharedTimelineTests(unittest.TestCase):

    def run_threads(self, clock, plans):
        """Each plan is a list of sleeps; returns each thread's wake-up times."""
        woke = {name: [] for name in plans}
        start = threading.Barrier(len(plans))

        def fly(name):
            with clock.participate():
                start.wait()        # all participants registered before anyone sleeps
                for seconds in plans[name]:
                    clock.sleep(seconds)
                    woke[name].append(clock.now())

        threads = [threading.Thread(target=fly, args=(n,)) for n in plans]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
            self.assertFalse(t.is_alive(), "a participant never woke: the clock deadlocked")
        return woke

    def test_each_thread_wakes_at_its_own_simulated_time(self):
        clock = SimClock()
        woke = self.run_threads(clock, {
            "Drone1": [5.0, 5.0, 5.0],
            "Drone2": [7.0, 1.0],
            "Drone3": [12.5],
            "Drone4": [0.0, 15.0],
        })
        self.assertEqual(woke["Drone1"], [5.0, 10.0, 15.0])
        self.assertEqual(woke["Drone2"], [7.0, 8.0])
        self.assertEqual(woke["Drone3"], [12.5])
        self.assertEqual(woke["Drone4"], [0.0, 15.0])
        self.assertEqual(clock.now(), 15.0)

    def test_deterministic_across_runs(self):
        plans = {f"Drone{i}": [0.1 * i, 2.0, 0.3 * i] for i in range(1, 5)}
        first = self.run_threads(SimClock(), plans)
        for _ in range(20):
            self.assertEqual(self.run_threads(SimClock(), plans), first)

    def test_time_does_not_pass_while_a_participant_computes(self):
        clock = SimClock()
        seen = {}
        computing = threading.Event()
        release = threading.Event()

        def sleeper():
            with clock.participate():
                computing.wait()
                clock.sleep(10.0)
                seen["sleeper"] = clock.now()

        def thinker():
            with clock.participate():
                computing.set()
                time.sleep(0.2)                # real work, no simulated time
                seen["during"] = clock.now()
                release.set()
                clock.sleep(1.0)
                seen["thinker"] = clock.now()

        a, b = threading.Thread(target=sleeper), threading.Thread(target=thinker)
        a.start(), b.start()
        a.join(5), b.join(5)
        self.assertEqual(seen["during"], 0.0)     # the sleeper could not move time alone
        self.assertEqual(seen["thinker"], 1.0)
        self.assertEqual(seen["sleeper"], 10.0)

    def test_leaving_lets_the_others_move(self):
        clock = SimClock()
        woke = self.run_threads(clock, {"short": [1.0], "long": [1.0, 50.0]})
        self.assertEqual(woke["long"], [1.0, 51.0])

    def test_a_non_participant_cannot_sleep_on_a_shared_timeline(self):
        clock = SimClock()
        entered, done = threading.Event(), threading.Event()

        def participant():
            with clock.participate():
                entered.set()
                done.wait(5)

        t = threading.Thread(target=participant)
        t.start()
        entered.wait(5)
        with self.assertRaises(RuntimeError):
            clock.sleep(1.0)
        with self.assertRaises(RuntimeError):
            clock.advance(1.0)
        done.set()
        t.join(5)

    def test_participating_twice_is_refused(self):
        clock = SimClock()
        with clock.participate():
            with self.assertRaises(RuntimeError):
                with clock.participate():
                    pass


class SameInstantOrderTests(unittest.TestCase):
    """A thread that reads what others did at an instant sees all of it.

    Threads due at one instant wake in an order the operating system picks.
    Phase 7 step 6 found an agent ticking at 30.0 s that saw its skill's
    ending at 30.0 s on some runs and not others. `sleep_after_others` is the
    fix; these force the race by making thread switches as frequent as
    Python allows.
    """

    TRIALS = 300

    def setUp(self):
        self.interval = sys.getswitchinterval()
        sys.setswitchinterval(1e-6)

    def tearDown(self):
        sys.setswitchinterval(self.interval)

    def trial(self, observer_sleep):
        """A worker ends something at 1.0 s; the observer, due then, reads it."""
        clock = SimClock()
        start = threading.Barrier(2)
        ended, seen = [], {}

        def worker():
            with clock.participate():
                start.wait()
                clock.sleep(1.0)
                ended.append(clock.now())
                clock.sleep(5.0)

        def observer():
            with clock.participate():
                start.wait()
                getattr(clock, observer_sleep)(1.0)
                seen["at"], seen["ended"] = clock.now(), list(ended)

        threads = [threading.Thread(target=worker), threading.Thread(target=observer)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
            self.assertFalse(t.is_alive(), "a participant never woke: the clock deadlocked")
        return seen

    def test_a_late_sleeper_always_sees_what_ended_at_its_instant(self):
        for _ in range(self.TRIALS):
            seen = self.trial("sleep_after_others")
            self.assertEqual(seen, {"at": 1.0, "ended": [1.0]})

    def test_a_late_sleeper_wakes_at_its_own_time(self):
        clock = SimClock()
        woke = {}
        start = threading.Barrier(3)

        def plain():
            with clock.participate():
                start.wait()
                clock.sleep(0.5)
                clock.sleep(0.5)            # due again at the late sleeper's instant
                clock.sleep(9.0)

        def late(name, seconds):
            with clock.participate():
                start.wait()
                clock.sleep_after_others(seconds)
                woke[name] = clock.now()

        threads = [threading.Thread(target=plain), threading.Thread(target=late, args=("a", 1.0)),
                   threading.Thread(target=late, args=("b", 1.0))]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
            self.assertFalse(t.is_alive(), "late sleepers waited for each other, or for nothing")
        self.assertEqual(woke, {"a": 1.0, "b": 1.0})

    def test_a_thread_leaving_at_the_instant_releases_a_late_sleeper(self):
        clock = SimClock()
        start = threading.Barrier(2)
        seen = {}

        def leaver():
            with clock.participate():
                start.wait()
                clock.sleep(2.0)
            seen["left"] = True

        def late():
            with clock.participate():
                start.wait()
                clock.sleep_after_others(2.0)
                seen["at"] = clock.now()

        threads = [threading.Thread(target=leaver), threading.Thread(target=late)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
            self.assertFalse(t.is_alive())
        self.assertEqual(seen, {"left": True, "at": 2.0})

    def test_a_late_sleep_does_not_make_a_thread_late_for_good(self):
        # A thread that once slept late, then ends something on a plain sleep,
        # is waited for like any other.
        for _ in range(self.TRIALS):
            clock = SimClock()
            start = threading.Barrier(2)
            ended, seen = [], {}

            def worker():
                with clock.participate():
                    start.wait()
                    clock.sleep_after_others(0.5)
                    clock.sleep(0.5)
                    ended.append(clock.now())
                    clock.sleep(5.0)

            def observer():
                with clock.participate():
                    start.wait()
                    clock.sleep_after_others(1.0)
                    seen["at"], seen["ended"] = clock.now(), list(ended)

            threads = [threading.Thread(target=worker), threading.Thread(target=observer)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=10)
                self.assertFalse(t.is_alive(), "a participant never woke: the clock deadlocked")
            self.assertEqual(seen, {"at": 1.0, "ended": [1.0]})

    def test_a_sleep_cut_short_leaves_nothing_behind(self):
        # Thread ids are reused, so a thread that leaves mid-sleep (an
        # exception) must not stay registered as asleep, or as late.
        clock = SimClock()
        joined, done = threading.Event(), threading.Event()
        cut = {}

        class Cut(Exception):
            pass

        real_wait = clock._cv.wait

        def wait(*args, **kwargs):
            if threading.get_ident() == cut.get("ident"):
                raise Cut()
            return real_wait(*args, **kwargs)

        clock._cv.wait = wait

        def holder():                       # keeps the timeline shared, awake
            with clock.participate():
                joined.set()
                done.wait(10)

        def sleeper():
            cut["ident"] = threading.get_ident()
            joined.wait(10)
            with self.assertRaises(Cut):
                with clock.participate():
                    clock.sleep_after_others(1.0)
            done.set()

        threads = [threading.Thread(target=holder), threading.Thread(target=sleeper)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
            self.assertFalse(t.is_alive())
        self.assertEqual((clock._wake_at, clock._late, clock._participants), ({}, set(), set()))

    def test_alone_or_unshared_it_is_a_plain_sleep(self):
        clock = SimClock()
        clock.sleep_after_others(2.5)
        self.assertEqual(clock.now(), 2.5)
        with clock.participate():
            clock.sleep_after_others(1.0)
        self.assertEqual(clock.now(), 3.5)
        tick = time.get_clock_info("monotonic").resolution
        real = RealClock()
        t0 = real.now()
        real.sleep_after_others(0.05)
        self.assertGreaterEqual(real.now() - t0, 0.05 - tick)

    def test_the_agent_ticks_after_the_others(self):
        # The fix is only a fix if the agent's tick uses it.
        import inspect
        from agentic_uav.agents import drone_agent
        source = inspect.getsource(drone_agent.DroneAgent.run)
        self.assertIn("self.clock.sleep_after_others(self.tick_s)", source)
        self.assertNotIn("self.clock.sleep(", source)


if __name__ == "__main__":
    unittest.main()
