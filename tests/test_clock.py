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
        t0 = clock.now()
        clock.sleep(0.01)
        self.assertGreaterEqual(clock.now() - t0, 0.009)

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


if __name__ == "__main__":
    unittest.main()
