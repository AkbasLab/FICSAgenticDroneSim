"""Phase 10 tests. Phase 7's messaging was proven under perfect delivery -
these tests prove the degraded model is honest: configured loss/latency
actually show up empirically, loss is only ever inferred by an agent from
what it can actually see (sequence gaps), not read off the model, and the
same seed reproduces the same run while a different seed doesn't.
"""

import os
import statistics
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fics_drone.agents.comms_estimator import CommsEstimator
from fics_drone.coordination.comms_conditions import NOMINAL, SEVERE
from fics_drone.coordination.message_bus import MessageBus
from fics_drone.coordination.network_model import NetworkModel, NetworkProfile, Partition
from fics_drone.coordination.protocols import MessageType


class TestNetworkModelStatistics(unittest.TestCase):
    def test_configured_packet_loss_lands_within_a_few_points_empirically(self):
        profile = NetworkProfile(name="lossy", packet_loss_probability=0.30)
        model = NetworkModel(profile, seed=1)
        trials = 5000
        lost = sum(1 for i in range(trials) if not model.transmit_to_recipient("A", "B", float(i))[0])
        self.assertAlmostEqual(lost / trials, 0.30, delta=0.03)

    def test_latency_mean_and_jitter_land_close_to_configured(self):
        profile = NetworkProfile(name="jittery", latency_ms_mean=150.0, latency_ms_jitter=50.0)
        model = NetworkModel(profile, seed=2)
        delays_ms = []
        for i in range(2000):
            delivered, deliver_at, _ = model.transmit_to_recipient("A", "B", 0.0)
            self.assertTrue(delivered)
            delays_ms.append(deliver_at * 1000.0)
        self.assertAlmostEqual(statistics.mean(delays_ms), 150.0, delta=10.0)
        self.assertAlmostEqual(statistics.pstdev(delays_ms), 50.0, delta=10.0)

    def test_latency_never_goes_negative_even_when_jitter_exceeds_the_mean(self):
        profile = NetworkProfile(name="huge_jitter", latency_ms_mean=10.0, latency_ms_jitter=100.0)
        model = NetworkModel(profile, seed=3)
        for i in range(2000):
            _, deliver_at, _ = model.transmit_to_recipient("A", "B", 0.0)
            self.assertGreaterEqual(deliver_at, 0.0)


class TestNetworkModelReproducibility(unittest.TestCase):
    def _draws(self, seed):
        model = NetworkModel(NOMINAL, seed=seed)
        return [model.transmit_to_recipient("A", "B", float(i)) for i in range(50)]

    def test_identical_seed_reproduces_identically(self):
        self.assertEqual(self._draws(42), self._draws(42))

    def test_different_seed_does_not_reproduce(self):
        self.assertNotEqual(self._draws(1), self._draws(2))


class TestRateLimit(unittest.TestCase):
    def test_messages_beyond_the_per_second_limit_are_refused(self):
        profile = NetworkProfile(name="limited", message_rate_limit=3.0)
        model = NetworkModel(profile, seed=0)
        allowed = [not model.check_rate_limit("A", now=0.1 * i) for i in range(10)]  # 10 sends in 1s
        self.assertEqual(sum(allowed), 3)

    def test_rate_limit_resets_after_the_window_passes(self):
        profile = NetworkProfile(name="limited", message_rate_limit=2.0)
        model = NetworkModel(profile, seed=0)
        self.assertFalse(model.check_rate_limit("A", now=0.0))
        self.assertFalse(model.check_rate_limit("A", now=0.1))
        self.assertTrue(model.check_rate_limit("A", now=0.2))  # 3rd within 1s - refused
        self.assertFalse(model.check_rate_limit("A", now=1.5))  # window has rolled past

    def test_bus_logs_rate_limited_sends_with_the_right_reason(self):
        profile = NetworkProfile(name="limited", message_rate_limit=1.0)
        bus = MessageBus(network_model=NetworkModel(profile, seed=0))
        bus.register("A")
        bus.register("B")
        bus.send(MessageType.HEARTBEAT, "A", {})
        bus.send(MessageType.HEARTBEAT, "A", {})  # same instant, 2nd one over the limit
        reasons = {e.reason for e in bus.log if not e.delivered}
        self.assertIn("rate_limited", reasons)


class TestPartition(unittest.TestCase):
    def test_blocks_only_the_named_pair_inside_the_window(self):
        p = Partition(a="A", b="B", start_t=10.0, end_t=20.0)
        self.assertTrue(p.blocks("A", "B", now=15.0))
        self.assertTrue(p.blocks("B", "A", now=15.0))  # symmetric
        self.assertFalse(p.blocks("A", "C", now=15.0))  # different pair
        self.assertFalse(p.blocks("A", "B", now=5.0))   # before the window
        self.assertFalse(p.blocks("A", "B", now=25.0))  # after the window

    def test_bus_drops_messages_between_a_partitioned_pair(self):
        profile = NetworkProfile(name="split", partitions=[Partition("A", "B", 0.0, 100.0)])
        bus = MessageBus(network_model=NetworkModel(profile, seed=0))
        bus.register("A")
        bus.register("B")
        bus.register("C")
        bus.send(MessageType.HEARTBEAT, "A", {}, recipients=["B", "C"])
        self.assertEqual(bus.receive_available("B"), [])  # partitioned from A
        self.assertEqual(len(bus.receive_available("C")), 1)  # not partitioned


class TestDelayedDeliveryAndExpiry(unittest.TestCase):
    def test_a_delayed_message_is_not_visible_before_its_deliver_at_time(self):
        profile = NetworkProfile(name="slow", latency_ms_mean=10_000.0, latency_ms_jitter=0.0)
        bus = MessageBus(network_model=NetworkModel(profile, seed=0))
        bus.register("A")
        bus.register("B")
        bus.send(MessageType.HEARTBEAT, "A", {})
        self.assertEqual(bus.receive_available("B"), [])  # 10s latency, read happens immediately

    def test_no_network_model_behaves_exactly_like_before_phase_10(self):
        bus = MessageBus()
        bus.register("A")
        bus.register("B")
        bus.send(MessageType.HEARTBEAT, "A", {})
        self.assertEqual(len(bus.receive_available("B")), 1)


class TestCommsEstimator(unittest.TestCase):
    def test_never_holds_a_reference_to_the_network_model_or_profile(self):
        est = CommsEstimator()
        for value in vars(est).values():
            self.assertNotIsInstance(value, NetworkModel)
            self.assertNotIsInstance(value, NetworkProfile)

    def test_sequence_gap_is_detected_as_loss(self):
        est = CommsEstimator()
        for seq in (1, 2, 4, 5):  # seq 3 never arrived
            msg = _msg(sender="A", seq=seq)
            est.observe(msg, now=float(seq))
        self.assertAlmostEqual(est.estimated_loss_rate("A"), 1 / 5)

    def test_no_gap_means_zero_estimated_loss(self):
        est = CommsEstimator()
        for seq in (1, 2, 3):
            est.observe(_msg(sender="A", seq=seq), now=float(seq))
        self.assertEqual(est.estimated_loss_rate("A"), 0.0)

    def test_unknown_sender_has_no_estimate_yet(self):
        est = CommsEstimator()
        self.assertIsNone(est.estimated_loss_rate("Nobody"))

    def test_estimates_higher_loss_under_severe_than_under_nominal_without_being_told(self):
        """The actual exit criterion: the estimator never sees which profile
        is active, only what did or didn't arrive (via sequence gaps) - but
        its own number comes out higher under severe regardless. Drives
        NetworkModel.transmit_to_recipient directly with explicit `now`
        values, rather than through a real-time MessageBus, so the result
        depends only on the configured packet loss, not on wall-clock/thread
        timing noise."""
        def estimated_loss(profile):
            model = NetworkModel(profile, seed=7)
            est = CommsEstimator()
            seq = 0
            for i in range(300):
                seq += 1
                delivered, deliver_at, _ = model.transmit_to_recipient("A", "B", now=float(i))
                if delivered:
                    est.observe(_msg(sender="A", seq=seq), now=deliver_at)
            return est.estimated_loss_rate("A") or 0.0

        self.assertGreater(estimated_loss(SEVERE), estimated_loss(NOMINAL))


def _msg(sender, seq):
    from fics_drone.coordination.protocols import Message
    return Message(id=seq, type=MessageType.HEARTBEAT, sender=sender, recipients=None,
                   created_t=float(seq), ttl_s=60.0, payload={}, seq=seq)


if __name__ == "__main__":
    unittest.main()
