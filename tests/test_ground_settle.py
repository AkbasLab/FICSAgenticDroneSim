"""The ground reference must only be recorded once the drone has stopped moving.
No simulator: the adapter is built without __init__ and its two RPC reads are faked."""

from types import SimpleNamespace

import pytest

from fics_drone.simulator.airsim_adapter import AirSimVehicleAdapter


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, dt):
        self.t += dt


def make_adapter(clock, z_of_t, speed_of_t):
    a = AirSimVehicleAdapter.__new__(AirSimVehicleAdapter)
    a.vehicle_name = "Drone1"
    a._get_position_ned = lambda: SimpleNamespace(z_val=z_of_t(clock.now()))
    a.get_speed = lambda: speed_of_t(clock.now())
    return a


def test_waits_out_a_fall_and_records_the_final_ground():
    clock = FakeClock()
    # falling (speed 4 m/s, z shrinking toward 29.25) until t=3, then still
    z = lambda t: 29.25 if t >= 3 else 29.25 - 4.0 * (3 - t)
    speed = lambda t: 0.0 if t >= 3 else 4.0
    a = make_adapter(clock, z, speed)
    assert a._wait_until_settled(sleep=clock.sleep, clock=clock.now) == pytest.approx(29.25)


def test_a_drone_already_at_rest_settles_after_the_window():
    clock = FakeClock()
    a = make_adapter(clock, lambda t: 10.0, lambda t: 0.0)
    assert a._wait_until_settled(sleep=clock.sleep, clock=clock.now) == 10.0
    assert clock.now() >= 1.0  # it did not accept the very first sample


def test_slow_sink_without_speed_is_not_settled():
    """Speed under the threshold but z still creeping more than the drift limit
    must keep resetting the streak, then time out."""
    clock = FakeClock()
    a = make_adapter(clock, lambda t: 10.0 + 0.2 * t, lambda t: 0.1)
    with pytest.raises(TimeoutError):
        a._wait_until_settled(sleep=clock.sleep, clock=clock.now)


def test_never_settling_times_out_instead_of_recording_a_bad_ground():
    clock = FakeClock()
    a = make_adapter(clock, lambda t: 5.0, lambda t: 3.0)
    with pytest.raises(TimeoutError, match="never settled"):
        a._wait_until_settled(sleep=clock.sleep, clock=clock.now)


class TestLandingEndCheck:
    """The landing must fail loudly if it ends away from the ground reference."""

    def _adapter(self, height):
        a = AirSimVehicleAdapter.__new__(AirSimVehicleAdapter)
        a.vehicle_name = "Drone1"
        a.get_height = lambda: height
        return a

    def test_ending_on_the_ground_reference_passes(self):
        self._adapter(0.0)._check_landed()
        self._adapter(-0.4)._check_landed()    # resting a little low
        self._adapter(1.2)._check_landed()     # a slightly higher patch of ground

    def test_the_observed_minus_11_8_is_a_failure(self):
        with pytest.raises(RuntimeError, match="-11.80 m"):
            self._adapter(-11.8)._check_landed()

    def test_landing_on_top_of_something_is_a_failure_too(self):
        with pytest.raises(RuntimeError, match=r"\+8\.70 m"):
            self._adapter(8.7)._check_landed()


class TestLandAsyncOnlyWhenHeldUp:
    """Root cause of the live -11.8 m landing: landAsync descends 0.2 m/s until contact, 60 s timeout.
    With no ground collision that is 12 m. It must not run when the drone is already at the ground."""

    def test_at_the_ground_reference_landasync_is_skipped(self):
        for h in (0.0, 0.05, 0.3, 0.9, -0.2):
            assert AirSimVehicleAdapter._needs_land_async(h) is False, h

    def test_clearly_above_the_ground_it_is_still_used(self):
        # e.g. resting on an awning 8.7 m up: something is holding it, landAsync can settle it there
        for h in (1.01, 2.0, 8.7):
            assert AirSimVehicleAdapter._needs_land_async(h) is True, h
